"""
Service for managing monitored systems
"""

import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models import HealthStatus, System, Task
from ..utils.logger import get_logger
from ..utils.yaml_loader import (
    config_to_json_serializable,
    flatten_config,
    validate_system_config,
    validate_task_type_config,
)

logger = get_logger(__name__)


class SystemManager:
    """Manages system registration and configuration"""

    @staticmethod
    def register_system(
        system_id: str,
        name: str,
        description: Optional[str],
        config: Dict[str, Any],
        db: Session,
        agent_id: Optional[int] = None,
    ) -> System:
        """
        Register a new monitored system
        
        Args:
            system_id: Unique system identifier
            name: Display name
            description: Description
            config: Full YAML config as dict
            db: Database session
            agent_id: Associated agent ID
            
        Returns:
            Created System object
            
        Raises:
            ValueError: If system already exists or config is invalid
        """
        # Check if system already exists
        existing = db.query(System).filter(System.system_id == system_id).first()
        if existing:
            logger.warning(f"System {system_id} already exists, updating")
            return SystemManager.update_system(system_id, name, description, config, db)
        
        # Validate config
        try:
            validate_system_config({"system": config})
        except Exception as e:
            logger.error(f"Invalid config for system {system_id}: {e}")
            raise ValueError(f"Invalid configuration: {e}")
        
        # Create system
        system = System(
            system_id=system_id,
            name=name,
            description=description,
            config=config_to_json_serializable(config),
            status=HealthStatus.UNKNOWN,
            agent_id=agent_id,
        )
        
        db.add(system)
        db.flush()  # Get the ID
        
        # Create tasks
        SystemManager._create_tasks_from_config(system, config, db)
        
        db.commit()
        logger.info(f"Registered system: {system_id}")
        
        return system

    @staticmethod
    def update_system(
        system_id: str,
        name: Optional[str],
        description: Optional[str],
        config: Optional[Dict[str, Any]],
        db: Session,
    ) -> System:
        """
        Update an existing system
        
        Args:
            system_id: System ID
            name: New name (if provided)
            description: New description (if provided)
            config: New config (if provided)
            db: Database session
            
        Returns:
            Updated System object
        """
        system = db.query(System).filter(System.system_id == system_id).first()
        if not system:
            raise ValueError(f"System {system_id} not found")
        
        if name:
            system.name = name
        if description:
            system.description = description
        
        if config:
            # Validate config
            try:
                validate_system_config({"system": config})
            except Exception as e:
                raise ValueError(f"Invalid configuration: {e}")
            
            system.config = config_to_json_serializable(config)
            
            # Delete old tasks
            db.query(Task).filter(Task.system_id == system.id).delete()
            
            # Create new tasks
            SystemManager._create_tasks_from_config(system, config, db)
        
        db.commit()
        logger.info(f"Updated system: {system_id}")
        
        return system

    @staticmethod
    def _create_tasks_from_config(system: System, config: Dict[str, Any], db: Session) -> None:
        """
        Create Task records from system config
        
        Args:
            system: System to create tasks for
            config: System configuration
            db: Database session
        """
        tasks = config.get("tasks", [])
        
        for i, task_config in enumerate(tasks):
            # Validate task config
            try:
                validate_task_type_config(task_config)
            except Exception as e:
                logger.warning(f"Invalid task config for {system.system_id}: {e}")
                continue
            
            task_id = task_config.get("name") or f"{system.system_id}-task-{i}"
            task_type = task_config.get("type", "http").lower()
            timeout = task_config.get("timeout", 5.0)
            max_retries = task_config.get("max_retries", 0)
            
            # Extract task-specific config
            task_specific_config = {
                k: v for k, v in task_config.items()
                if k not in ("name", "type", "timeout", "max_retries")
            }
            
            task = Task(
                task_id=task_id,
                system_id=system.id,
                name=task_config.get("name", f"Task {i}"),
                task_type=task_type,
                config=task_specific_config,
                timeout=timeout,
                max_retries=max_retries,
                status=HealthStatus.UNKNOWN,
            )
            
            db.add(task)
        
        db.flush()
        logger.debug(f"Created {len(tasks)} tasks for system {system.system_id}")

    @staticmethod
    def get_system(system_id: str, db: Session) -> Optional[System]:
        """Get system by ID"""
        return db.query(System).filter(System.system_id == system_id).first()

    @staticmethod
    def list_systems(db: Session, skip: int = 0, limit: int = 20) -> tuple[list[System], int]:
        """
        List all systems
        
        Returns:
            Tuple of (systems list, total count)
        """
        total = db.query(System).count()
        systems = db.query(System).offset(skip).limit(limit).all()
        return systems, total

    @staticmethod
    def delete_system(system_id: str, db: Session) -> bool:
        """
        Delete a system and all associated data
        
        Returns:
            True if deleted, False if not found
        """
        system = db.query(System).filter(System.system_id == system_id).first()
        if not system:
            return False
        
        db.delete(system)
        db.commit()
        logger.info(f"Deleted system: {system_id}")
        return True
