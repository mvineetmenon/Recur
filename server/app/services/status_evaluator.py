"""
Service for evaluating system health status recursively
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import HealthStatus, System, SystemDependency, Task, TaskResult
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

        statuses: List[HealthStatus] = []
        for task in system.tasks:
            result = latest.get(task.id)
            if result:
                statuses.append(result.status)
            else:
                statuses.append(HealthStatus.UNKNOWN)

        return statuses

    @staticmethod
    def _latest_results_for_tasks(tasks: List[Task], db: Session) -> Dict[int, TaskResult]:
        """
        Fetch the most recent TaskResult for each task in a single query.

        Only the newest row per task (max id) is fetched, so query cost stays
        flat no matter how much result history has accumulated.

        Returns a mapping of task primary key -> latest result.
        """
        if not tasks:
            return {}

        task_ids = [task.id for task in tasks]
        latest_ids = (
            db.query(func.max(TaskResult.id).label("latest_id"))
            .filter(TaskResult.task_id.in_(task_ids))
            .group_by(TaskResult.task_id)
            .subquery()
        )
        results = (
            db.query(TaskResult)
            .join(latest_ids, TaskResult.id == latest_ids.c.latest_id)
            .all()
        )

        return {result.task_id: result for result in results}

    @staticmethod
    def _get_dependency_statuses(system: System, db: Session, _seen: set) -> List[HealthStatus]:
        """
        Recursively get statuses of all dependent systems
        """
        statuses: List[HealthStatus] = []

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
    def _task_dict(task: Task, result: Optional[TaskResult]) -> Dict[str, Any]:
        """Build one task entry for tree payloads (latest result, or UNKNOWN)"""
        if result:
            return {
                "task_id": task.task_id,
                "name": task.name,
                "task_type": task.task_type,
                "status": result.status,
                "duration_ms": result.duration_ms,
                "error_message": result.error_message,
                "output_data": result.output_data,
            }
        return {
            "task_id": task.task_id,
            "name": task.name,
            "task_type": task.task_type,
            "status": HealthStatus.UNKNOWN,
            "duration_ms": None,
            "error_message": None,
            "output_data": None,
        }

    @staticmethod
    def _build_tree(system: System, db: Session, seen: set) -> Dict[str, Any]:
        """Assemble one level of the system tree (recursion stack in `seen`)"""
        tree: Dict[str, Any] = {
            "system_id": system.system_id,
            "name": system.name,
            "description": system.description,
            "status": system.status,
            "last_check_time": system.last_check_time,
            "last_error": system.last_error,
            "tasks": [],
            "dependencies": [],
        }

        # Add task results (one bounded query for the whole level)
        latest = StatusEvaluator._latest_results_for_tasks(system.tasks, db)
        for task in system.tasks:
            tree["tasks"].append(StatusEvaluator._task_dict(task, latest.get(task.id)))

        # Recursively add dependencies
        for dep in system.dependencies:
            if dep.child_system:
                dep_tree = StatusEvaluator.get_system_tree(dep.child_system, db, seen)
                tree["dependencies"].append(dep_tree)

        return tree

    @staticmethod
    def get_system_forest(roots: List[System], db: Session) -> List[Dict[str, Any]]:
        """
        Build the forest of dependency trees for the given root systems.

        Bulk-loads all systems, dependency edges, tasks, and the latest task
        result per task (a constant number of queries, independent of
        topology size), then assembles the nested trees in Python. A system
        shared by several parents is built once and referenced at every
        position; dependency cycles are cut with an empty stub.
        """
        systems: Dict[int, System] = {system.id: system for system in db.query(System).all()}

        children_of: Dict[int, List[int]] = {}
        for edge in db.query(SystemDependency).order_by(SystemDependency.id).all():
            children_of.setdefault(edge.parent_system_id, []).append(edge.child_system_id)

        tasks_by_system: Dict[int, List[Task]] = {}
        for task in db.query(Task).order_by(Task.id).all():
            tasks_by_system.setdefault(task.system_id, []).append(task)

        all_tasks = [task for tasks in tasks_by_system.values() for task in tasks]
        latest = StatusEvaluator._latest_results_for_tasks(all_tasks, db)

        memo: Dict[int, Dict[str, Any]] = {}
        in_progress: set = set()

        def build(system: System) -> Dict[str, Any]:
            if system.id in memo:
                return memo[system.id]
            if system.id in in_progress:
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
            in_progress.add(system.id)
            node: Dict[str, Any] = {
                "system_id": system.system_id,
                "name": system.name,
                "description": system.description,
                "status": system.status,
                "last_check_time": system.last_check_time,
                "last_error": system.last_error,
                "tasks": [
                    StatusEvaluator._task_dict(task, latest.get(task.id))
                    for task in tasks_by_system.get(system.id, [])
                ],
                "dependencies": [
                    build(systems[child_id])
                    for child_id in children_of.get(system.id, [])
                    if child_id in systems
                ],
            }
            in_progress.discard(system.id)
            memo[system.id] = node
            return node

        return [build(root) for root in roots]

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

        task_statuses: Dict[str, int] = {}
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
