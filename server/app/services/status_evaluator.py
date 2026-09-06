"""
Service for evaluating system health status recursively
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import HealthStatus, System, Task, TaskResult
from ..utils.logger import get_logger

logger = get_logger(__name__)


class StatusEvaluator:
    """Evaluates overall system status based on task and dependency results"""

    @staticmethod
    def evaluate_system_status(system: System, db: Session) -> HealthStatus:
        """
        Recursively evaluate system status based on tasks and dependencies
        
        A system is UP only if:
        1. All its tasks are UP, AND
        2. All its dependent systems are UP (recursive)
        
        Args:
            system: System to evaluate
            db: Database session
            
        Returns:
            Overall status for the system
        """
        # Get latest task results
        task_statuses = StatusEvaluator._get_task_statuses(system, db)
        
        # If no tasks, check dependencies
        if not task_statuses:
            dep_statuses = StatusEvaluator._get_dependency_statuses(system, db)
            if not dep_statuses:
                return HealthStatus.UNKNOWN
            return HealthStatus.UP if all(s == HealthStatus.UP for s in dep_statuses) else HealthStatus.DOWN
        
        # All tasks must be UP
        tasks_ok = all(status == HealthStatus.UP for status in task_statuses)
        
        if not tasks_ok:
            logger.debug(f"System {system.system_id}: tasks not all UP")
            return HealthStatus.DOWN
        
        # Check dependencies
        dep_statuses = StatusEvaluator._get_dependency_statuses(system, db)
        
        if dep_statuses:
            deps_ok = all(status == HealthStatus.UP for status in dep_statuses)
            if not deps_ok:
                logger.debug(f"System {system.system_id}: dependencies not all UP")
                return HealthStatus.DOWN
        
        return HealthStatus.UP

    @staticmethod
    def _get_task_statuses(system: System, db: Session) -> List[HealthStatus]:
        """Get statuses of all tasks for a system"""
        statuses = []
        
        for task in system.tasks:
            # Get most recent result
            latest_result = (
                db.query(TaskResult)
                .filter(TaskResult.task_id == task.id)
                .order_by(TaskResult.created_at.desc())
                .first()
            )
            
            if latest_result:
                statuses.append(latest_result.status)
            else:
                statuses.append(HealthStatus.UNKNOWN)
        
        return statuses

    @staticmethod
    def _get_dependency_statuses(system: System, db: Session) -> List[HealthStatus]:
        """
        Recursively get statuses of all dependent systems
        """
        statuses = []
        
        for dep in system.dependencies:
            child_system = dep.child_system
            if child_system:
                status = StatusEvaluator.evaluate_system_status(child_system, db)
                statuses.append(status)
        
        return statuses

    @staticmethod
    def get_system_tree(system: System, db: Session) -> Dict[str, Any]:
        """
        Build complete system tree with all statuses and task results
        
        Args:
            system: Root system
            db: Database session
            
        Returns:
            Nested dictionary representing the system tree
        """
        tree = {
            "system_id": system.system_id,
            "name": system.name,
            "description": system.description,
            "status": system.status,
            "last_check_time": system.last_check_time,
            "last_error": system.last_error,
            "tasks": [],
            "dependencies": [],
        }

        # Add task results
        for task in system.tasks:
            latest_result = (
                db.query(TaskResult)
                .filter(TaskResult.task_id == task.id)
                .order_by(TaskResult.created_at.desc())
                .first()
            )
            
            if latest_result:
                tree["tasks"].append({
                    "task_id": task.task_id,
                    "name": task.name,
                    "type": task.task_type,
                    "status": latest_result.status,
                    "duration_ms": latest_result.duration_ms,
                    "error": latest_result.error_message,
                })
        
        # Recursively add dependencies
        for dep in system.dependencies:
            if dep.child_system:
                dep_tree = StatusEvaluator.get_system_tree(dep.child_system, db)
                tree["dependencies"].append(dep_tree)
        
        return tree

    @staticmethod
    def get_system_health_summary(system: System, db: Session) -> Dict[str, Any]:
        """
        Get a summary of system health without full tree details
        
        Args:
            system: System to summarize
            db: Database session
            
        Returns:
            Health summary
        """
        status = StatusEvaluator.evaluate_system_status(system, db)
        
        # Count tasks by status
        task_results = (
            db.query(TaskResult)
            .join(Task)
            .filter(Task.system_id == system.id)
            .order_by(TaskResult.created_at.desc())
        ).all()
        
        task_statuses = {}
        seen_tasks = set()
        
        for result in task_results:
            if result.task_id not in seen_tasks:
                status_val = result.status.value
                task_statuses[status_val] = task_statuses.get(status_val, 0) + 1
                seen_tasks.add(result.task_id)
        
        return {
            "system_id": system.system_id,
            "name": system.name,
            "status": status,
            "last_check_time": system.last_check_time,
            "task_count": len(system.tasks),
            "task_statuses": task_statuses,
            "dependency_count": len(system.dependencies),
        }
