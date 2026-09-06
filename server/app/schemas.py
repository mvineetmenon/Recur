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


class TaskConfig(BaseModel):
    """Task configuration (polymorphic based on type)"""

    task_type: str
    config: Dict[str, Any]


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


class SystemDependencyResponse(BaseModel):
    """Dependency information in tree view"""

    id: Optional[int]
    name: str
    status: HealthStatus
    last_check_time: Optional[datetime]
    tasks: List[TaskResultResponse] = []
    dependencies: List["SystemDependencyResponse"] = []

    class Config:
        from_attributes = True


class SystemTreeResponse(BaseModel):
    """Full system dependency tree"""

    system_id: str
    name: str
    description: Optional[str]
    status: HealthStatus
    last_check_time: Optional[datetime]
    last_error: Optional[str]
    tasks: List[TaskResultResponse] = []
    dependencies: List[SystemDependencyResponse] = []

    class Config:
        from_attributes = True


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
    agent_id: Optional[str]

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
    description: Optional[str]
    config: Dict[str, Any]
    agent_id: Optional[int]


# ==================== Status Report Schemas ====================


class StatusReportRequest(BaseModel):
    """Status report from agent"""

    agent_id: str
    timestamp: datetime
    system_status: Dict[str, Any]  # Full recursive status tree


class StatusHistoryResponse(BaseModel):
    """Historical status entry"""

    id: int
    system_id: str
    agent_id: str
    report_timestamp: datetime
    received_at: datetime
    status: HealthStatus

    class Config:
        from_attributes = True


# ==================== Health Check Schemas ====================


class HealthCheckResponse(BaseModel):
    """Server health check response"""

    status: str = "healthy"
    timestamp: datetime
    version: str
    database: str


class CheckTriggerResponse(BaseModel):
    """Response when triggering a manual check"""

    agent_id: str
    status: str  # "checking", "scheduled", "error"
    task_count: int
    message: Optional[str]


# ==================== Error Schemas ====================


class ErrorResponse(BaseModel):
    """Standard error response"""

    error: str
    detail: Optional[str]
    timestamp: datetime
    request_id: Optional[str]


# Update forward references for recursive models
SystemDependencyResponse.model_rebuild()
