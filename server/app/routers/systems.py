"""
System management endpoints
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import System, SystemDependency
from ..schemas import (
    SystemCreateRequest,
    SystemForestResponse,
    SystemListResponse,
    SystemResponse,
    SystemTreeResponse,
    SystemUpdateRequest,
)
from ..services.status_evaluator import StatusEvaluator
from ..services.system_manager import SystemManager
from ..utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["systems"])


@router.post("/systems", response_model=SystemResponse, status_code=status.HTTP_201_CREATED)
async def create_system(
    system_data: SystemCreateRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Register a new monitored system

    The config should be the full YAML system configuration (already parsed).
    """
    try:
        system = SystemManager.register_system(
            system_id=system_data.system_id,
            name=system_data.name,
            description=system_data.description,
            config=system_data.config,
            db=db,
            agent_id=system_data.agent_id,
        )

        return SystemResponse.model_validate(system)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to create system: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create system",
        )


@router.put("/systems/{system_id}", response_model=SystemResponse)
async def update_system(
    system_id: str,
    system_data: SystemUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Update an existing monitored system (partial update)

    Any of name/description/config may be provided; omitted fields are kept.
    """
    try:
        system = SystemManager.update_system(
            system_id=system_id,
            name=system_data.name,
            description=system_data.description,
            config=system_data.config,
            db=db,
        )

        return SystemResponse.model_validate(system)

    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"System '{system_id}' not found",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to update system: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update system",
        )


@router.get("/systems", response_model=SystemListResponse)
async def list_systems(
    db: Annotated[Session, Depends(get_db)],
    skip: int = Query(0, ge=0),
    limit: int = Query(config.DEFAULT_PAGE_SIZE, ge=1, le=config.MAX_PAGE_SIZE),
):
    """
    List all monitored systems
    """
    systems, total = SystemManager.list_systems(db, skip=skip, limit=limit)

    return SystemListResponse(
        total=total,
        systems=[SystemResponse.model_validate(s) for s in systems],
    )


@router.get("/systems/forest", response_model=SystemForestResponse)
async def list_system_forest(
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get all systems as a forest of dependency trees

    Returns only root systems (systems that no other system depends on),
    each with its full nested tree of tasks and dependencies. This is the
    hierarchical view of the whole monitoring topology.

    NOTE: must stay above the ``/systems/{system_id}`` route so the literal
    path "forest" is not captured as a system id.
    """
    child_ids = select(SystemDependency.child_system_id)
    roots = db.query(System).filter(~System.id.in_(child_ids)).order_by(System.name).all()

    trees = StatusEvaluator.get_system_forest(roots, db)

    return SystemForestResponse(
        root_count=len(trees),
        roots=[SystemTreeResponse(**tree) for tree in trees],
    )


@router.get("/systems/{system_id}", response_model=SystemResponse)
async def get_system(
    system_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get information about a specific system
    """
    system = SystemManager.get_system(system_id, db)

    if not system:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"System '{system_id}' not found",
        )

    return SystemResponse.model_validate(system)


@router.get("/systems/{system_id}/tree", response_model=SystemTreeResponse)
async def get_system_tree(
    system_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get full dependency tree for a system with current status

    This endpoint returns the complete hierarchical structure of a system,
    including all dependencies and their current health check statuses.
    """
    system = SystemManager.get_system(system_id, db)

    if not system:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"System '{system_id}' not found",
        )

    tree = StatusEvaluator.get_system_tree(system, db)

    return SystemTreeResponse(**tree)


@router.get("/systems/{system_id}/health", response_model=dict)
async def get_system_health_summary(
    system_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get a quick health summary for a system (without full tree details)
    """
    system = SystemManager.get_system(system_id, db)

    if not system:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"System '{system_id}' not found",
        )

    summary = StatusEvaluator.get_system_health_summary(system, db)

    return summary


@router.delete("/systems/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_system(
    system_id: str,
    db: Annotated[Session, Depends(get_db)],
):
    """
    Delete a monitored system and all associated data
    """
    success = SystemManager.delete_system(system_id, db)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"System '{system_id}' not found",
        )

    return None
