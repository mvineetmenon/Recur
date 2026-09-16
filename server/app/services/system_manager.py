"""
Service for managing monitored systems
"""

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models import Agent, HealthStatus, StatusReport, System, SystemDependency, Task, TaskResult
from ..utils.logger import get_logger
from ..utils.yaml_loader import (
    config_to_json_serializable,
    validate_system_config,
    validate_task_type_config,
)

logger = get_logger(__name__)


def _slugify(value: Any) -> str:
    """Derive a stable slug from a system name or id"""
    return str(value or "unknown").strip().lower().replace(" ", "-")


def _delete_system_tasks(db: Session, system_pk: int) -> None:
    """
    Delete a system's tasks FK-safely.

    A plain bulk ``DELETE`` on tasks would orphan (or violate, on databases
    with enforced FKs) the TaskResult rows that reference them, so the
    results are removed first.
    """
    task_ids = [
        row[0]
        for row in db.query(Task.id).filter(Task.system_id == system_pk).all()
    ]
    if task_ids:
        db.query(TaskResult).filter(TaskResult.task_id.in_(task_ids)).delete(
            synchronize_session=False
        )
    db.query(Task).filter(Task.system_id == system_pk).delete(synchronize_session=False)


def _delete_system_reports(db: Session, system_pk: int) -> None:
    """
    Delete a system's status reports FK-safely (task results first).

    StatusReport.system_id is a non-nullable FK with no cascade, so the rows
    must be removed explicitly before the system itself.
    """
    report_ids = [
        row[0]
        for row in db.query(StatusReport.id).filter(StatusReport.system_id == system_pk).all()
    ]
    if report_ids:
        db.query(TaskResult).filter(TaskResult.status_report_id.in_(report_ids)).delete(
            synchronize_session=False
        )
    db.query(StatusReport).filter(StatusReport.system_id == system_pk).delete(
        synchronize_session=False
    )


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
        Register a new monitored system (including nested dependencies)

        Args:
            system_id: Unique system identifier
            name: Display name
            description: Description
            config: Full YAML config as dict
            db: Database session
            agent_id: Associated agent (database id)

        Returns:
            Created System object

        Raises:
            ValueError: If config is invalid or agent does not exist
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

        # Validate agent reference
        if agent_id is not None:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if not agent:
                raise ValueError(f"Agent with id {agent_id} not found")

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

        # Create tasks and nested dependency systems
        SystemManager._create_tasks_from_config(system, config, db)
        SystemManager._register_dependencies(system, config, db, agent_id)

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

        Returns:
            Updated System object
        """
        system = db.query(System).filter(System.system_id == system_id).first()
        if not system:
            raise ValueError(f"System {system_id} not found")

        if name is not None:
            system.name = name
        if description is not None:
            system.description = description

        if config is not None:
            # Validate config
            try:
                validate_system_config({"system": config})
            except Exception as e:
                raise ValueError(f"Invalid configuration: {e}")

            system.config = config_to_json_serializable(config)

            # Delete old tasks (and their results) and dependency links;
            # children are upserted below
            _delete_system_tasks(db, system.id)
            db.query(SystemDependency).filter(
                SystemDependency.parent_system_id == system.id
            ).delete(synchronize_session=False)
            db.expire_all()

            # Create new tasks and re-register nested dependencies
            SystemManager._create_tasks_from_config(system, config, db)
            SystemManager._register_dependencies(system, config, db, system.agent_id)

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
    def _register_dependencies(
        parent: System,
        config: Dict[str, Any],
        db: Session,
        agent_id: Optional[int],
    ) -> None:
        """
        Recursively register nested dependency systems and link them.

        Child system ids are stable: explicit child `id` if given, otherwise
        derived from the child name, always prefixed with the parent id
        (e.g. `web/api`, `web/api/db`).
        """
        for dep in config.get("dependencies", []):
            if not isinstance(dep, dict):
                logger.warning(f"Ignoring malformed dependency in {parent.system_id}")
                continue

            child_slug = str(dep.get("id") or _slugify(dep.get("name")))
            child_system_id = f"{parent.system_id}/{child_slug}"

            # Validate child config (lenient: skip malformed children with a warning)
            try:
                validate_system_config({"system": dep})
            except Exception as e:
                logger.warning(f"Skipping invalid dependency {child_system_id}: {e}")
                continue

            child = db.query(System).filter(System.system_id == child_system_id).first()
            if child is None:
                child = System(
                    system_id=child_system_id,
                    name=dep.get("name") or child_slug,
                    description=dep.get("description"),
                    config=config_to_json_serializable(dep),
                    status=HealthStatus.UNKNOWN,
                    agent_id=agent_id,
                )
                db.add(child)
                db.flush()
                SystemManager._create_tasks_from_config(child, dep, db)
            else:
                # Re-registration is idempotent: refresh definition and tasks
                child.name = dep.get("name") or child.name
                if dep.get("description") is not None:
                    child.description = dep["description"]
                child.config = config_to_json_serializable(dep)
                _delete_system_tasks(db, child.id)
                SystemManager._create_tasks_from_config(child, dep, db)

            # Create or refresh the dependency link
            link = (
                db.query(SystemDependency)
                .filter(
                    SystemDependency.parent_system_id == parent.id,
                    SystemDependency.child_system_id == child.id,
                )
                .first()
            )
            if link is None:
                link = SystemDependency(
                    parent_system_id=parent.id,
                    child_system_id=child.id,
                    criticality=str(dep.get("criticality", "HIGH")),
                )
                db.add(link)
                db.flush()
            else:
                link.criticality = str(dep.get("criticality", "HIGH"))

            # Recurse into deeper levels
            SystemManager._register_dependencies(child, dep, db, agent_id)

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

        # Remove status reports (with their task results) first: the FK is
        # non-nullable and has no cascade
        _delete_system_reports(db, system.id)

        # Remove dependency links pointing at this system
        db.query(SystemDependency).filter(
            SystemDependency.child_system_id == system.id
        ).delete(synchronize_session=False)
        db.query(SystemDependency).filter(
            SystemDependency.parent_system_id == system.id
        ).delete(synchronize_session=False)

        db.expire_all()
        db.delete(system)
        db.commit()
        logger.info(f"Deleted system: {system_id}")
        return True
