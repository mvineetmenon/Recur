"""
Service for processing health check reports from agents
"""

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from ..models import HealthStatus, StatusReport, System, SystemDependency, Task, TaskResult
from ..services.system_manager import _slugify
from ..utils.logger import get_logger
from ..utils.yaml_loader import config_to_json_serializable
from .status_evaluator import StatusEvaluator

logger = get_logger(__name__)


def _is_ancestor_or_self(db: Session, pk: int, system: System) -> bool:
    """
    True when the system with primary key `pk` is `system` itself or one of
    its ancestors (through any parent chain).
    """
    if pk == system.id:
        return True

    frontier = {system.id}
    seen = {system.id}
    while frontier:
        parents = {
            row[0]
            for row in db.query(SystemDependency.parent_system_id)
            .filter(SystemDependency.child_system_id.in_(frontier))
            .all()
        }
        if pk in parents:
            return True
        parents -= seen
        seen |= parents
        frontier = parents
    return False


class HealthCheckProcessor:
    """Processes health check reports from agents"""

    @staticmethod
    def process_status_report(
        agent_id: int,
        system_id: str,
        report_timestamp: datetime,
        report_data: Dict[str, Any],
        db: Session,
    ) -> StatusReport:
        """
        Process an incoming status report from an agent

        The report contains the full recursive status tree. Nested systems are
        resolved (or auto-created) and every level's task results are recorded,
        so the server-side recursive evaluation can roll status up the tree.

        Args:
            agent_id: ID of reporting agent
            system_id: ID of system being reported
            report_timestamp: When report was generated
            report_data: Full status tree data
            db: Database session

        Returns:
            Created StatusReport object
        """
        start_time = datetime.utcnow()

        # Find system
        system = db.query(System).filter(System.system_id == system_id).first()
        if not system:
            logger.warning(f"Report for unknown system: {system_id}")
            raise ValueError(f"System {system_id} not found")

        # Create status report
        status_report = StatusReport(
            agent_id=agent_id,
            system_id=system.id,
            report_timestamp=report_timestamp,
            report_data=report_data,
        )

        db.add(status_report)
        db.flush()  # Get the ID

        # Process task results recursively (root first, then nested levels)
        HealthCheckProcessor._process_system_report(
            system,
            report_data,
            status_report.id,
            report_timestamp,
            agent_id,
            db,
        )

        # Evaluate and persist status for every level of the tree,
        # bottom-up, so the parent reflects the full recursive state
        new_status = HealthCheckProcessor._refresh_statuses(system, report_timestamp, db)
        system.last_error = report_data.get("error")

        # Record processing duration
        status_report.processing_duration_ms = (
            datetime.utcnow() - start_time
        ).total_seconds() * 1000

        db.commit()
        logger.info(f"Processed report for {system_id}: status={new_status}")

        return status_report

    @staticmethod
    def _resolve_nested_system(
        parent: System,
        dep_data: Dict[str, Any],
        agent_id: int,
        db: Session,
    ) -> System:
        """
        Resolve a nested system referenced in a report, auto-creating it
        (with its tasks and the parent link) when it is not registered yet.
        """
        child_id = dep_data.get("system_id") or _slugify(dep_data.get("name"))

        child = db.query(System).filter(System.system_id == child_id).first()
        if child is None:
            # Agents report nested systems by local slug, while registered
            # children carry the parent-prefixed id (e.g. `webstack/db`).
            # Resolve the prefixed form so reports match registered children.
            child_id = f"{parent.system_id}/{child_id}"
            child = db.query(System).filter(System.system_id == child_id).first()
        if child is None:
            child = System(
                system_id=child_id,
                name=dep_data.get("name") or child_id,
                config=config_to_json_serializable(dep_data),
                status=HealthStatus.UNKNOWN,
                agent_id=agent_id,
            )
            db.add(child)
            db.flush()

            # Materialize tasks from the reported results so later reports
            # can be matched against real Task rows
            for task_data in dep_data.get("tasks", []):
                task_name = task_data.get("task_id") or task_data.get("name")
                if not task_name:
                    continue
                existing = (
                    db.query(Task)
                    .filter(Task.system_id == child.id, Task.task_id == task_name)
                    .first()
                )
                if existing is None:
                    db.add(
                        Task(
                            task_id=task_name,
                            system_id=child.id,
                            name=task_data.get("name") or task_name,
                            task_type=str(task_data.get("type", "http")).lower(),
                            config={},
                            status=HealthStatus.UNKNOWN,
                        )
                    )
            db.flush()

        # A report may reference an ancestor (or the parent itself) as a
        # "dependency"; linking it would create a cycle that makes recursive
        # evaluation/refresh loop forever. Record the results but skip the link.
        if _is_ancestor_or_self(db, child.id, parent):
            logger.warning(
                f"Skipping dependency link {parent.system_id} -> {child.system_id}: "
                "report references an ancestor, which would create a cycle"
            )
            return child

        # Ensure the parent -> child dependency link exists
        link = (
            db.query(SystemDependency)
            .filter(
                SystemDependency.parent_system_id == parent.id,
                SystemDependency.child_system_id == child.id,
            )
            .first()
        )
        if link is None:
            db.add(
                SystemDependency(
                    parent_system_id=parent.id,
                    child_system_id=child.id,
                    criticality="HIGH",
                )
            )
            db.flush()

        return child

    @staticmethod
    def _process_system_report(
        system: System,
        data: Dict[str, Any],
        status_report_id: int,
        report_timestamp: datetime,
        agent_id: int,
        db: Session,
    ) -> None:
        """
        Record task results for one system level of a report, then recurse
        into nested dependency results.
        """
        for task_data in data.get("tasks", []):
            HealthCheckProcessor._process_task_result(
                system, task_data, status_report_id, report_timestamp, db
            )

        for dep_data in data.get("dependencies", []):
            if not isinstance(dep_data, dict):
                continue
            child = HealthCheckProcessor._resolve_nested_system(system, dep_data, agent_id, db)
            HealthCheckProcessor._process_system_report(
                child, dep_data, status_report_id, report_timestamp, agent_id, db
            )

        db.flush()

    @staticmethod
    def _process_task_result(
        system: System,
        task_data: Dict[str, Any],
        status_report_id: int,
        report_timestamp: datetime,
        db: Session,
    ) -> None:
        """Create a TaskResult row and refresh the Task status for one task"""
        task_id = task_data.get("task_id") or task_data.get("name")
        status_str = str(task_data.get("status", "UNKNOWN")).upper()

        try:
            status = HealthStatus[status_str]
        except KeyError:
            status = HealthStatus.UNKNOWN

        if not task_id:
            return

        # Find task (auto-create when the report references an unregistered task)
        task = db.query(Task).filter(Task.system_id == system.id, Task.task_id == task_id).first()
        if not task:
            logger.warning(f"Report contains unknown task: {task_id}")
            task = Task(
                task_id=task_id,
                system_id=system.id,
                name=task_data.get("name") or task_id,
                task_type=str(task_data.get("type", "http")).lower(),
                config={},
                status=HealthStatus.UNKNOWN,
            )
            db.add(task)
            db.flush()

        result = TaskResult(
            task_id=task.id,
            status_report_id=status_report_id,
            status=status,
            duration_ms=task_data.get("duration_ms"),
            error_message=task_data.get("error"),
            output_data=task_data.get("output"),
        )

        db.add(result)

        # Update task status
        task.status = status
        task.last_check_time = report_timestamp
        task.last_duration_ms = task_data.get("duration_ms")
        task.last_error = task_data.get("error")

    @staticmethod
    def _refresh_statuses(
        system: System,
        report_timestamp: datetime,
        db: Session,
        _seen: set | None = None,
    ) -> HealthStatus:
        """
        Evaluate and persist status for a system and all of its dependencies.

        Children are refreshed first so that every level stores a consistent
        status for display; the returned value is the root system's status.
        `_seen` guards against pre-existing cycles in the dependency graph.
        """
        seen = _seen if _seen is not None else set()
        if system.id in seen:
            return system.status
        seen.add(system.id)
        try:
            for dep in system.dependencies:
                if dep.child_system:
                    HealthCheckProcessor._refresh_statuses(
                        dep.child_system, report_timestamp, db, seen
                    )

            # Evaluate with a fresh stack: `seen` already contains this
            # system (added above), and the evaluator has its own cycle guard.
            system.status = StatusEvaluator.evaluate_system_status(system, db)
            system.last_check_time = report_timestamp
            return system.status
        finally:
            seen.discard(system.id)

    @staticmethod
    def get_task_history(
        task_id: str,
        system_id: str,
        db: Session,
        limit: int = 100,
    ) -> List[TaskResult]:
        """
        Get historical results for a task

        Args:
            task_id: Task ID
            system_id: System ID
            db: Database session
            limit: Max results to return

        Returns:
            List of TaskResult objects
        """
        results = (
            db.query(TaskResult)
            .join(StatusReport)
            .join(System)
            .join(Task)
            .filter(
                System.system_id == system_id,
                Task.task_id == task_id,
            )
            .order_by(TaskResult.created_at.desc())
            .limit(limit)
            .all()
        )

        return results

    @staticmethod
    def get_system_history(
        system_id: str,
        db: Session,
        limit: int = 50,
    ) -> List[StatusReport]:
        """
        Get historical status reports for a system

        Args:
            system_id: System ID
            db: Database session
            limit: Max reports to return

        Returns:
            List of StatusReport objects
        """
        reports = (
            db.query(StatusReport)
            .join(System)
            .filter(System.system_id == system_id)
            .order_by(StatusReport.received_at.desc())
            .limit(limit)
            .all()
        )

        return reports
