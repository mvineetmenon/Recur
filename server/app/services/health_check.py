"""
Service for processing health check reports from agents
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import HealthStatus, StatusReport, System, Task, TaskResult
from ..utils.logger import get_logger
from .status_evaluator import StatusEvaluator

logger = get_logger(__name__)


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
        
        # Process task results recursively
        HealthCheckProcessor._process_task_results(
            report_data,
            system,
            status_report,
            db,
        )
        
        # Evaluate overall system status
        new_status = StatusEvaluator.evaluate_system_status(system, db)
        system.status = new_status
        system.last_check_time = report_timestamp
        system.last_error = report_data.get("error")
        
        # Record processing duration
        status_report.processing_duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        db.commit()
        logger.info(f"Processed report for {system_id}: status={new_status}")
        
        return status_report

    @staticmethod
    def _process_task_results(
        report_data: Dict[str, Any],
        system: System,
        status_report: StatusReport,
        db: Session,
    ) -> None:
        """
        Process task results from report and create TaskResult records
        
        Args:
            report_data: Status report data
            system: System these results belong to
            status_report: StatusReport object
            db: Database session
        """
        tasks_data = report_data.get("tasks", [])
        
        for task_data in tasks_data:
            task_id = task_data.get("task_id") or task_data.get("name")
            status_str = task_data.get("status", "UNKNOWN").upper()
            
            try:
                status = HealthStatus[status_str]
            except KeyError:
                status = HealthStatus.UNKNOWN
            
            # Find task
            task = db.query(Task).filter(
                Task.system_id == system.id,
                Task.task_id == task_id,
            ).first()
            
            if not task:
                logger.warning(f"Report contains unknown task: {task_id}")
                continue
            
            # Create task result
            result = TaskResult(
                task_id=task.id,
                status_report_id=status_report.id,
                status=status,
                duration_ms=task_data.get("duration_ms"),
                error_message=task_data.get("error"),
                output_data=task_data.get("output"),
            )
            
            db.add(result)
            
            # Update task status
            task.status = status
            task.last_check_time = status_report.report_timestamp
            task.last_duration_ms = task_data.get("duration_ms")
            task.last_error = task_data.get("error")
        
        db.flush()

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
