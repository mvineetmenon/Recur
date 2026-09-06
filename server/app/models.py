"""
Database models for Recur monitoring platform
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

from . import config

# Status enums
class HealthStatus(str, PyEnum):
    UP = "UP"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"
    DEGRADED = "DEGRADED"


Base = declarative_base()


class Agent(Base):
    """Remote agent that executes health checks"""

    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    agent_id = Column(String(255), unique=True, nullable=False, index=True)
    hostname = Column(String(255), nullable=False)
    ip_address = Column(String(45), nullable=False)
    version = Column(String(50), default="0.1.0")
    
    last_heartbeat = Column(DateTime, default=datetime.utcnow, nullable=False)
    registered_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    status = Column(Enum(HealthStatus), default=HealthStatus.UNKNOWN)
    is_active = Column(Boolean, default=True)
    
    # Metadata
    os_type = Column(String(50))
    cpu_count = Column(Integer)
    python_version = Column(String(50))
    
    # Relationships
    systems = relationship("System", back_populates="agent")
    status_reports = relationship("StatusReport", back_populates="agent")

    def __repr__(self) -> str:
        return f"<Agent {self.agent_id}>"


class System(Base):
    """Monitored system definition"""

    __tablename__ = "systems"

    id = Column(Integer, primary_key=True)
    system_id = Column(String(255), unique=True, nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    
    name = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Configuration
    config = Column(JSON, nullable=False)  # Full YAML config as JSON
    
    # Current status
    status = Column(Enum(HealthStatus), default=HealthStatus.UNKNOWN)
    last_check_time = Column(DateTime)
    last_error = Column(Text)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    agent = relationship("Agent", back_populates="systems")
    tasks = relationship("Task", back_populates="system", cascade="all, delete-orphan")
    dependencies = relationship(
        "SystemDependency",
        foreign_keys="SystemDependency.parent_system_id",
        back_populates="parent_system",
        cascade="all, delete-orphan",
    )
    status_history = relationship("StatusReport", back_populates="system")

    def __repr__(self) -> str:
        return f"<System {self.system_id}>"


class Task(Base):
    """Individual health check task"""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(255), nullable=False, index=True)
    system_id = Column(Integer, ForeignKey("systems.id"), nullable=False)
    
    name = Column(String(255), nullable=False)
    task_type = Column(String(50), nullable=False)  # http, tcp, command, ping, script
    
    # Task configuration
    config = Column(JSON, nullable=False)  # Type-specific config as JSON
    
    # Current status
    status = Column(Enum(HealthStatus), default=HealthStatus.UNKNOWN)
    last_check_time = Column(DateTime)
    last_duration_ms = Column(Float)  # milliseconds
    last_error = Column(Text)
    
    # Timeout and retry settings
    timeout = Column(Float, default=5.0)  # seconds
    max_retries = Column(Integer, default=0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    system = relationship("System", back_populates="tasks")
    results = relationship("TaskResult", back_populates="task", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Task {self.task_id}>"


class SystemDependency(Base):
    """Dependency relationship between systems"""

    __tablename__ = "system_dependencies"

    id = Column(Integer, primary_key=True)
    parent_system_id = Column(Integer, ForeignKey("systems.id"), nullable=False)
    child_system_id = Column(Integer, ForeignKey("systems.id"), nullable=False)
    
    # Dependency strength/weight for future use
    criticality = Column(String(50), default="HIGH")  # HIGH, MEDIUM, LOW
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    parent_system = relationship(
        "System",
        foreign_keys=[parent_system_id],
        back_populates="dependencies",
    )
    child_system = relationship("System", foreign_keys=[child_system_id])

    def __repr__(self) -> str:
        return f"<Dependency {self.parent_system_id} -> {self.child_system_id}>"


class StatusReport(Base):
    """Complete status report from an agent"""

    __tablename__ = "status_reports"

    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    system_id = Column(Integer, ForeignKey("systems.id"), nullable=False)
    
    report_timestamp = Column(DateTime, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Full report as JSON for archival
    report_data = Column(JSON, nullable=False)
    
    # Processing metadata
    processing_duration_ms = Column(Float)
    
    # Relationships
    agent = relationship("Agent", back_populates="status_reports")
    system = relationship("System", back_populates="status_history")
    task_results = relationship("TaskResult", back_populates="status_report")

    def __repr__(self) -> str:
        return f"<StatusReport {self.id} from {self.agent_id}>"


class TaskResult(Base):
    """Individual task result from a status report"""

    __tablename__ = "task_results"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    status_report_id = Column(Integer, ForeignKey("status_reports.id"), nullable=False)
    
    status = Column(Enum(HealthStatus), nullable=False)
    duration_ms = Column(Float)
    error_message = Column(Text)
    
    # Additional output
    output_data = Column(JSON)  # Type-specific output
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    task = relationship("Task", back_populates="results")
    status_report = relationship("StatusReport", back_populates="task_results")

    def __repr__(self) -> str:
        return f"<TaskResult {self.id}>"


# Database initialization
engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in config.DATABASE_URL else {},
    echo=config.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
