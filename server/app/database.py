"""
Database initialization and session management
"""

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from . import config
from .models import Base

# Create engine
engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in config.DATABASE_URL else {},
    echo=config.DEBUG,
    pool_pre_ping=True,  # Test connections before using them
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_agent_token_hash() -> None:
    """Add Agent.token_hash to databases created before the column existed.

    create_all() never alters existing tables, so databases from earlier
    versions get the column via a portable ALTER TABLE (works on SQLite and
    PostgreSQL alike).
    """
    inspector = inspect(engine)
    if "agents" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agents")}
    if "token_hash" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE agents ADD COLUMN token_hash VARCHAR(128)")


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)
    _migrate_agent_token_hash()


def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
