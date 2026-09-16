"""
Service for evaluating system health status recursively
"""

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from ..models import HealthStatus, System, Task, TaskResult
from ..utils.logger import get_logger

logger = get_logger(__name__)


class StatusEvaluator:
    """Evaluates overall system status based on task and dependency results"""

    @staticmethod
    def evaluate_system_status(
        system: System,
        db: Session,
        _seen: set | None = None,
    ) -> HealthStatus:
        """
        Recursively evaluate system status based on tasks and dependencies

        A system is UP only if:
        1. All its tasks are UP, AND
        2. All its dependent systems are UP (recursive)

        Args:
            system: System to evaluate
            db: Database session
            _seen: Internal cycle guard (systems already on the recursion stack)

        Returns:
            Overall status for the system
        """
        seen = _seen if _seen is not None else set()
        if system.id in seen:
            # Cycle guard: a dependency loop must not recurse forever
            return HealthStatus.UNKNOWN
        seen.add(system.id)
        try:
            # Get latest task results and recursive dependency statuses
            task_statuses = StatusEvaluator._get_task_statuses(system, db)
            dep_statuses = StatusEvaluator._get_dependency_statuses(system, db, seen)

            # No data at all (no tasks, no dependencies)
            if not task_statuses and not dep_statuses:
                return HealthStatus.UNKNOWN

            # Any DOWN anywhere makes the system DOWN
            if any(s == HealthStatus.DOWN for s in task_statuses) or any(
                s == HealthStatus.DOWN for s in dep_statuses
            ):
                return HealthStatus.DOWN

            # UP only when every task and every dependency is UP
            if all(s == HealthStatus.UP for s in task_statuses) and all(
                s == HealthStatus.UP for s in dep_statuses
            ):
                return HealthStatus.UP

            # Otherwise some data is missing (UNKNOWN) or mixed
            return HealthStatus.UNKNOWN
        finally:
            # Keep `seen` as the recursion stack so shared (diamond)
            # dependencies are still evaluated on every path
            seen.discard(system.id)

    @staticmethod
    def _get_task_statuses(system: System, db: Session) -> List[HealthStatus]:
        """Get statuses of all tasks for a system (latest result per task)"""
        latest = StatusEvaluator._latest_results_for_tasks(system.tasks, db)

        statuses = []
        for task in system.tasks:
            result = latest.get(task.id)
            if result:
                statuses.append(result.status)
            else:
                statuses.append(HealthStatus.UNKNOWN)

        return statuses

    @staticmethod
    def _latest_results_for_tasks(
        tasks: List[Task], db: Session
    ) -> Dict[int, TaskResult]:
        """
        Fetch the most recent TaskResult for each task in a single query.

        Returns a mapping of task primary key -> latest result.
        """
        if not tasks:
            return {}

        task_ids = [task.id for task in tasks]
        results = (
            db.query(TaskResult)
            .filter(TaskResult.task_id.in_(task_ids))
            .order_by(TaskResult.created_at.desc(), TaskResult.id.desc())
            .all()
        )

        latest: Dict[int, TaskResult] = {}
        for result in results:
            if result.task_id not in latest:
                latest[result.task_id] = result
        return latest

    @staticmethod
    def _get_dependency_statuses(
        system: System, db: Session, _seen: set
    ) -> List[HealthStatus]:
        """
        Recursively get statuses of all dependent systems
        """
        statuses = []

        for dep in system.dependencies:
            child_system = dep.child_system
            if child_system:
                status = StatusEvaluator.evaluate_system_status(child_system, db, _seen)
                statuses.append(status)

        return statuses

    @staticmethod
    def get_system_tree(
        system: System,
        db: Session,
        _seen: set | None = None,
    ) -> Dict[str, Any]:
        """
        Build complete system tree with all statuses and task results

        Args:
            system: Root system
            db: Database session
            _seen: Internal cycle guard (systems already on the recursion stack)

        Returns:
            Nested dictionary representing the system tree
        """
        seen = _seen if _seen is not None else set()
        if system.id in seen:
            # Cycle guard: stop instead of recursing forever
            logger.warning(f"Dependency cycle detected at {system.system_id}")
            return {
                "system_id": system.system_id,
                "name": system.name,
                "description": system.description,
                "status": system.status,
                "last_check_time": system.last_check_time,
                "last_error": system.last_error,
                "tasks": [],
                "dependencies": [],
            }
        seen.add(system.id)
        try:
            return StatusEvaluator._build_tree(system, db, seen)
        finally:
            seen.discard(system.id)

    @staticmethod
    def _build_tree(
        system: System, db: Session, seen: set
    ) -> Dict[str, Any]:
        """Assemble one level of the system tree (recursion stack in `seen`)"""
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

        # Add task results (one query for the whole level)
        latest = StatusEvaluator._latest_results_for_tasks(system.tasks, db)
        for task in system.tasks:
            result = latest.get(task.id)
            if result:
                tree["tasks"].append({
                    "task_id": task.task_id,
                    "name": task.name,
                    "task_type": task.task_type,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "error_message": result.error_message,
                    "output_data": result.output_data,
                })
            else:
                tree["tasks"].append({
                    "task_id": task.task_id,
                    "name": task.name,
                    "task_type": task.task_type,
                    "status": HealthStatus.UNKNOWN,
                    "duration_ms": None,
                    "error_message": None,
                    "output_data": None,
                })

        # Recursively add dependencies
        for dep in system.dependencies:
            if dep.child_system:
                dep_tree = StatusEvaluator.get_system_tree(dep.child_system, db, seen)
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
