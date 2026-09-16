"""
Database models for Recur monitoring platform
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Status enums


class HealthStatus(str, PyEnum):
    UP = "UP"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"
    DEGRADED = "DEGRADED"


class Base(DeclarativeBase):
    """Declarative base for all ORM models"""


class Agent(Base):
    """Remote agent that executes health checks"""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hostname: Mapped[str] = mapped_column(String(255))
    ip_address: Mapped[str] = mapped_column(String(45))
    version: Mapped[Optional[str]] = mapped_column(String(50), default="0.1.0")

    last_heartbeat: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    status: Mapped[HealthStatus] = mapped_column(Enum(HealthStatus), default=HealthStatus.UNKNOWN)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Metadata
    os_type: Mapped[Optional[str]] = mapped_column(String(50))
    cpu_count: Mapped[Optional[int]] = mapped_column(Integer)
    python_version: Mapped[Optional[str]] = mapped_column(String(50))

    # Relationships
    systems: Mapped[List["System"]] = relationship(back_populates="agent")
    status_reports: Mapped[List["StatusReport"]] = relationship(back_populates="agent")

    def __repr__(self) -> str:
        return f"<Agent {self.agent_id}>"


class System(Base):
    """Monitored system definition"""

    __tablename__ = "systems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    agent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agents.id"))

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Configuration
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)  # Full YAML config as JSON

    # Current status
    status: Mapped[HealthStatus] = mapped_column(Enum(HealthStatus), default=HealthStatus.UNKNOWN)
    last_check_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    agent: Mapped[Optional["Agent"]] = relationship(back_populates="systems")
    tasks: Mapped[List["Task"]] = relationship(
        back_populates="system", cascade="all, delete-orphan"
    )
    dependencies: Mapped[List["SystemDependency"]] = relationship(
        "SystemDependency",
        foreign_keys="SystemDependency.parent_system_id",
        back_populates="parent_system",
        cascade="all, delete-orphan",
    )
    status_history: Mapped[List["StatusReport"]] = relationship(back_populates="system")

    def __repr__(self) -> str:
        return f"<System {self.system_id}>"


class Task(Base):
    """Individual health check task"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(255), index=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("systems.id"))

    name: Mapped[str] = mapped_column(String(255))
    task_type: Mapped[str] = mapped_column(String(50))  # http, tcp, command, ping, script

    # Task configuration (type-specific settings as JSON)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Current status
    status: Mapped[HealthStatus] = mapped_column(Enum(HealthStatus), default=HealthStatus.UNKNOWN)
    last_check_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_duration_ms: Mapped[Optional[float]] = mapped_column(Float)  # milliseconds
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    # Timeout and retry settings
    timeout: Mapped[float] = mapped_column(Float, default=5.0)  # seconds
    max_retries: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    system: Mapped["System"] = relationship(back_populates="tasks")
    results: Mapped[List["TaskResult"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Task {self.task_id}>"


class SystemDependency(Base):
    """Dependency relationship between systems"""

    __tablename__ = "system_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_system_id: Mapped[int] = mapped_column(ForeignKey("systems.id"))
    child_system_id: Mapped[int] = mapped_column(ForeignKey("systems.id"))

    # Dependency strength/weight for future use
    criticality: Mapped[Optional[str]] = mapped_column(
        String(50), default="HIGH"
    )  # HIGH, MEDIUM, LOW

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    parent_system: Mapped["System"] = relationship(
        "System",
        foreign_keys=[parent_system_id],
        back_populates="dependencies",
    )
    child_system: Mapped["System"] = relationship("System", foreign_keys=[child_system_id])

    def __repr__(self) -> str:
        return f"<Dependency {self.parent_system_id} -> {self.child_system_id}>"


class StatusReport(Base):
    """Complete status report from an agent"""

    __tablename__ = "status_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    system_id: Mapped[int] = mapped_column(ForeignKey("systems.id"))

    report_timestamp: Mapped[datetime] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Full report as JSON for archival
    report_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Processing metadata
    processing_duration_ms: Mapped[Optional[float]] = mapped_column(Float)

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="status_reports")
    system: Mapped["System"] = relationship(back_populates="status_history")
    task_results: Mapped[List["TaskResult"]] = relationship(back_populates="status_report")

    def __repr__(self) -> str:
        return f"<StatusReport {self.id} from {self.agent_id}>"


class TaskResult(Base):
    """Individual task result from a status report"""

    __tablename__ = "task_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    status_report_id: Mapped[int] = mapped_column(ForeignKey("status_reports.id"))

    status: Mapped[HealthStatus] = mapped_column(Enum(HealthStatus), nullable=False)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Additional output
    output_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)  # Type-specific output

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    task: Mapped["Task"] = relationship(back_populates="results")
    status_report: Mapped["StatusReport"] = relationship(back_populates="task_results")

    def __repr__(self) -> str:
        return f"<TaskResult {self.id}>"
