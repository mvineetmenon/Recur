"""
Agent management endpoints
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import Agent, HealthStatus, StatusReport, TaskResult
from ..schemas import AgentListResponse, AgentRegisterRequest, AgentRegisterResponse, AgentResponse
from ..security import authenticate_agent, client_ip, hash_token, new_agent_token, verify_enrollment
from ..utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agents"])


@router.post(
    "/agents/register", response_model=AgentRegisterResponse, status_code=status.HTTP_201_CREATED
)
async def register_agent(
    agent_data: AgentRegisterRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Register a new agent

    Agents must register with the server before they can submit status reports.
    First registration issues a bearer token (returned once as ``agent_token``).
    Re-registration rotates the agent's token and returns the new plaintext,
    which is the recovery path for agents that lost their token file (e.g.
    upgraded from a pre-token build). When ``RECUR_ENROLLMENT_TOKEN`` is
    configured, registration requires the token (``X-Recur-Enrollment-Token``
    header) unless the agent already holds a valid token.
    """
    if not verify_enrollment(request, db, agent_data.agent_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Registration requires a valid enrollment token or the agent's existing token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Check if agent already exists
        existing = db.query(Agent).filter(Agent.agent_id == agent_data.agent_id).first()

        if existing:
            # Update existing agent (optional fields only overwrite when provided)
            existing.hostname = agent_data.hostname
            existing.ip_address = agent_data.ip_address
            existing.version = agent_data.version
            if agent_data.os_type is not None:
                existing.os_type = agent_data.os_type
            if agent_data.cpu_count is not None:
                existing.cpu_count = agent_data.cpu_count
            if agent_data.python_version is not None:
                existing.python_version = agent_data.python_version
            existing.last_heartbeat = datetime.utcnow()

            # Rotate the token on re-registration (recovery path for lost
            # token files; in closed mode the request is gated by
            # verify_enrollment above).
            token = new_agent_token()
            existing.token_hash = hash_token(token)

            db.commit()
            logger.info(
                "Updated agent registration: %s (token rotated) (from %s)",
                agent_data.agent_id,
                client_ip(request),
            )

            base = AgentResponse.model_validate(existing)
            return AgentRegisterResponse(**base.model_dump(), agent_token=token)

        # Create new agent (issue its bearer token; the plaintext is returned
        # exactly once, in this response)
        token = new_agent_token()
        agent = Agent(
            agent_id=agent_data.agent_id,
            hostname=agent_data.hostname,
            ip_address=agent_data.ip_address,
            version=agent_data.version or "0.1.0",
            status=HealthStatus.UNKNOWN,
            is_active=True,
            os_type=agent_data.os_type,
            cpu_count=agent_data.cpu_count,
            python_version=agent_data.python_version,
            token_hash=hash_token(token),
        )

        db.add(agent)
        db.commit()

        if not config.ENROLLMENT_TOKEN:
            logger.warning(
                "Registered new agent %s (%s) via OPEN enrollment (set RECUR_ENROLLMENT_TOKEN "
                "to require one) (from %s)",
                agent_data.agent_id,
                agent_data.hostname,
                client_ip(request),
            )
        else:
            logger.info(
                "Registered new agent: %s (%s) (from %s)",
                agent_data.agent_id,
                agent_data.hostname,
                client_ip(request),
            )

        base = AgentResponse.model_validate(agent)
        return AgentRegisterResponse(**base.model_dump(), agent_token=token)

    except Exception as e:
        logger.error(f"Failed to register agent: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register agent",
        )


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    db: Annotated[Session, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(config.DEFAULT_PAGE_SIZE, ge=1, le=config.MAX_PAGE_SIZE),
    active_only: bool = False,
):
    """
    List all registered agents

    Args:
        skip: Number of agents to skip (pagination)
        limit: Maximum number of agents to return
        active_only: Only return active agents
    """
    query = db.query(Agent)

    if active_only:
        query = query.filter(Agent.is_active.is_(True))

    total = query.count()
    agents = query.offset(skip).limit(limit).all()

    return AgentListResponse(
        total=total,
        agents=[AgentResponse.model_validate(a) for a in agents],
    )


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get information about a specific agent
    """
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    return AgentResponse.model_validate(agent)


@router.get("/agents/{agent_id}/systems", response_model=dict)
async def get_agent_systems(
    agent_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get list of systems managed by an agent
    """
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    systems = agent.systems or []

    return {
        "agent_id": agent_id,
        "system_count": len(systems),
        "systems": [
            {
                "system_id": s.system_id,
                "name": s.name,
                "status": s.status,
            }
            for s in systems
        ],
    }


@router.post("/agents/{agent_id}/check", status_code=status.HTTP_202_ACCEPTED)
async def trigger_agent_check(
    agent_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Trigger an immediate health check on an agent

    This is an optional feature that allows manual triggering of checks.
    The agent would need to implement a polling mechanism or webhook.
    """
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    # In a real implementation, this would send a command to the agent
    # For now, just return a placeholder response

    return {
        "agent_id": agent_id,
        "status": "check_requested",
        "message": "Check requested - agent will run on next interval",
    }


@router.put("/agents/{agent_id}/heartbeat")
async def agent_heartbeat(
    agent_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    agent: Annotated[Agent, Depends(authenticate_agent)],
):
    """
    Record a heartbeat from an agent (keep-alive)

    Requires the agent's bearer token, which must belong to the agent named in
    the URL.
    """
    if agent.agent_id != agent_id:
        logger.warning(
            "Heartbeat for agent %s rejected: token belongs to %s (from %s)",
            agent_id,
            agent.agent_id,
            client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not belong to this agent",
        )

    agent.last_heartbeat = datetime.utcnow()

    # Update status if agent was previously offline
    if agent.status == HealthStatus.DOWN:
        agent.status = HealthStatus.UNKNOWN

    db.commit()

    return {
        "agent_id": agent_id,
        "status": "heartbeat_received",
        "timestamp": datetime.utcnow().isoformat(),
    }


def _delete_agent_related(db: Session, agent: Agent) -> None:
    """
    Delete the agent's status reports and their task results.

    StatusReport.agent_id is a non-nullable FK with no cascade, so the rows
    must be removed explicitly before the agent itself (otherwise the delete
    fails with an IntegrityError).
    """
    report_ids = [
        row[0] for row in db.query(StatusReport.id).filter(StatusReport.agent_id == agent.id).all()
    ]
    if report_ids:
        db.query(TaskResult).filter(TaskResult.status_report_id.in_(report_ids)).delete(
            synchronize_session=False
        )
    db.query(StatusReport).filter(StatusReport.agent_id == agent.id).delete(
        synchronize_session=False
    )


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Remove an agent from the system
    """
    agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    _delete_agent_related(db, agent)
    db.expire_all()
    db.delete(agent)
    db.commit()

    logger.info("Deleted agent: %s (from %s)", agent_id, client_ip(request))

    return None
