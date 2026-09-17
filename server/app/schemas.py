"""
Pydantic schemas for API request/response validation
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .models import HealthStatus

# ==================== Agent Schemas ====================


class AgentRegisterRequest(BaseModel):
    """Agent registration request"""

    agent_id: str = Field(..., min_length=1, max_length=255)
    hostname: str = Field(..., min_length=1, max_length=255)
    ip_address: str = Field(..., min_length=1, max_length=45)
    version: Optional[str] = "0.1.0"
    os_type: Optional[str] = None
    cpu_count: Optional[int] = None
    python_version: Optional[str] = None


class AgentResponse(BaseModel):
    """Agent information response"""

    id: int
    agent_id: str
    hostname: str
    ip_address: str
    version: str
    last_heartbeat: datetime
    registered_at: datetime
    status: HealthStatus
    is_active: bool

    class Config:
        from_attributes = True


class AgentListResponse(BaseModel):
    """List of agents"""

    total: int
    agents: List[AgentResponse]


# ==================== Task Schemas ====================


class TaskResultResponse(BaseModel):
    """Result of a single task"""

    task_id: str
    name: str
    task_type: str
    status: HealthStatus
    duration_ms: Optional[float]
    error_message: Optional[str]
    output_data: Optional[Dict[str, Any]]

    class Config:
        from_attributes = True


# ==================== System Schemas ====================


class SystemTaskRequest(BaseModel):
    """Task within a system configuration"""

    name: str
    task_type: str = Field(..., pattern="^(http|https|tcp|command|ping|script)$")
    timeout: float = Field(default=5.0, ge=0.1, le=30.0)
    max_retries: int = Field(default=0, ge=0, le=3)
    config: Dict[str, Any]


class SystemTreeResponse(BaseModel):
    """Full system dependency tree"""

    system_id: str
    name: str
    description: Optional[str]
    status: HealthStatus
    last_check_time: Optional[datetime]
    last_error: Optional[str]
    tasks: List[TaskResultResponse] = []
    dependencies: List["SystemTreeResponse"] = []

    class Config:
        from_attributes = True


class SystemForestResponse(BaseModel):
    """All systems rendered as a forest of dependency trees

    Only root systems (those that no other system depends on) appear at the
    top level; their dependencies are nested recursively.

    ``root_count`` is the number of top-level roots, NOT the total number of
    systems in the forest (unlike ``total`` in ``SystemListResponse``).
    """

    root_count: int
    roots: List[SystemTreeResponse] = []


class SystemResponse(BaseModel):
    """System information response"""

    id: int
    system_id: str
    name: str
    description: Optional[str]
    status: HealthStatus
    last_check_time: Optional[datetime]
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime
    agent_id: Optional[int]

    class Config:
        from_attributes = True


class SystemListResponse(BaseModel):
    """List of systems"""

    total: int
    systems: List[SystemResponse]


class SystemCreateRequest(BaseModel):
    """Create system request"""

    system_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    config: Dict[str, Any]
    agent_id: Optional[int] = None


class SystemUpdateRequest(BaseModel):
    """Update system request (partial)"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


# ==================== Status Report Schemas ====================


class StatusReportRequest(BaseModel):
    """Status report from agent"""

    agent_id: str
    timestamp: datetime
    system_status: Dict[str, Any]  # Full recursive status tree


# ==================== Health Check Schemas ====================


class HealthCheckResponse(BaseModel):
    """Server health check response"""

    status: str = "healthy"
    timestamp: datetime
    version: str
    database: str


# Update forward references for recursive models
SystemTreeResponse.model_rebuild()
