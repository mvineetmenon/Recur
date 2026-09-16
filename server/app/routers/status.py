"""
Status report endpoints
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Agent
from ..schemas import HealthCheckResponse, StatusReportRequest
from ..services.health_check import HealthCheckProcessor
from ..utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["status"])


@router.post("/status", response_model=dict)
async def submit_status_report(
    report: StatusReportRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Accept a status report from an agent

    This endpoint receives the complete status tree from an agent and processes it,
    updating all task results and system statuses in the database.
    """
    try:
        # Find agent
        agent = db.query(Agent).filter(Agent.agent_id == report.agent_id).first()
        if not agent:
            logger.warning(f"Status report from unknown agent: {report.agent_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent '{report.agent_id}' not found. Please register first.",
            )

        # Get system ID from report
        system_status = report.system_status
        system_id = system_status.get("system_id") or system_status.get("name", "").lower().replace(
            " ", "-"
        )

        if not system_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Report is missing 'system_id' (or a 'name' to derive it from)",
            )

        # Process the report
        status_report = HealthCheckProcessor.process_status_report(
            agent_id=agent.id,
            system_id=system_id,
            report_timestamp=report.timestamp,
            report_data=system_status,
            db=db,
        )

        return {
            "status": "accepted",
            "report_id": status_report.id,
            "processed_at": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process status report: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to process report: {e}",
        )


@router.get("/systems/{system_id}/history", response_model=dict)
async def get_system_status_history(
    system_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(50, ge=1, le=1000),
):
    """
    Get historical status reports for a system

    Args:
        system_id: System ID
        limit: Maximum number of reports to return
    """
    reports = HealthCheckProcessor.get_system_history(system_id, db, limit=limit)

    if not reports:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No history found for system {system_id}",
        )

    return {
        "system_id": system_id,
        "count": len(reports),
        "history": [
            {
                "report_id": r.id,
                "timestamp": r.report_timestamp,
                "received_at": r.received_at,
            }
            for r in reports
        ],
    }


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Server health check endpoint"""
    return HealthCheckResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        version="0.1.0",
        database="ready",
    )
