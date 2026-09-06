"""
Pytest configuration for Recur tests

This uses pytest_configure hook which runs BEFORE test collection,
ensuring database patches are applied before any test modules are imported.
"""

import os
import sys
from typing import Generator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# CRITICAL: Use pytest_configure which runs BEFORE test collection
def pytest_configure(config):
    """
    Configure pytest - runs BEFORE test collection.
    Patch the database module before any test imports app.
    """
    # Setup path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    
    # Create in-memory test engine
    SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
    
    from app.models import Base
    
    test_engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
    
    # Enable foreign keys
    @event.listens_for(test_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    
    # Create tables
    Base.metadata.create_all(bind=test_engine)
    
    # Patch database module BEFORE app is imported by tests
    import app.database as database_module
    database_module.engine = test_engine
    database_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    
    # Store for fixture access
    config.test_engine = test_engine
    
    # Register custom markers
    config.addinivalue_line("markers", "integration: integration tests")
    config.addinivalue_line("markers", "unit: unit tests")
    config.addinivalue_line("markers", "slow: slow tests")


@pytest.fixture(scope="session")
def test_engine(pytestconfig):
    """Provide test engine from config"""
    yield pytestconfig.test_engine
    pytestconfig.test_engine.dispose()


@pytest.fixture
def test_db(test_engine) -> Generator[Session, None, None]:
    """
    Function-scoped database session with transaction rollback for test isolation
    """
    TestSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(test_db):
    """
    FastAPI TestClient with test database
    Database is already patched in pytest_configure before test collection
    """
    from app.main import app
    from app.database import get_db
    
    # Override get_db dependency
    def override_get_db():
        try:
            yield test_db
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    
    from fastapi.testclient import TestClient
    with TestClient(app) as test_client:
        yield test_client
    
    app.dependency_overrides.clear()


# Pre-seeded fixtures
@pytest.fixture
def db_with_agent(test_db):
    """Database with a test agent"""
    from app.models import Agent, HealthStatus
    
    agent = Agent(
        agent_id="test-agent-1",
        hostname="test.local",
        ip_address="192.168.1.100",
        status=HealthStatus.UP,
    )
    test_db.add(agent)
    test_db.commit()
    test_db.refresh(agent)
    
    return test_db, agent


@pytest.fixture
def db_with_system(db_with_agent):
    """Database with test agent and system"""
    from app.models import System, HealthStatus
    
    test_db, agent = db_with_agent
    
    system = System(
        system_id="test-system-1",
        agent_id=agent.id,
        name="Test System",
        config={"name": "Test", "tasks": []},
        status=HealthStatus.UP,
    )
    test_db.add(system)
    test_db.commit()
    test_db.refresh(system)
    
    return test_db, agent, system
