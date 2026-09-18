"""
Pytest configuration for Recur tests

All tests standardize on `server.app.*` imports. The database module is
patched with a shared in-memory SQLite engine (StaticPool => one connection)
BEFORE any test module imports the app. Each test gets its own session with a
savepoint, so mid-test commits are rolled back at teardown (full isolation).
"""

import os
import sys

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Make the repository root importable so `server.app` resolves from anywhere
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def pytest_configure(config):
    """Patch the database module BEFORE any test imports the app."""
    from server.app import database as database_module
    from server.app.models import Base

    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    # pysqlite's legacy transaction handling breaks SAVEPOINT isolation
    # (an implicit BEGIN is not issued, so releasing the outermost savepoint
    # commits the data). Disable the driver's transaction management and
    # emit BEGIN explicitly, as recommended in the pysqlite dialect docs.
    @event.listens_for(test_engine, "connect")
    def disable_pysqlite_tx(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(test_engine, "begin")
    def emit_begin(conn):
        conn.exec_driver_sql("BEGIN")

    # Enable foreign keys
    @event.listens_for(test_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)

    # Patch database module so the app uses the in-memory engine
    database_module.engine = test_engine
    database_module.SessionLocal = SessionLocal_for(test_engine)

    # Store for fixture access
    config.test_engine = test_engine

    # Register custom markers
    config.addinivalue_line("markers", "integration: integration tests")
    config.addinivalue_line("markers", "unit: unit tests")
    config.addinivalue_line("markers", "slow: slow running tests")


def SessionLocal_for(engine):
    """Session factory bound to the given engine"""
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session")
def test_engine(pytestconfig):
    """Provide shared in-memory test engine"""
    yield pytestconfig.test_engine
    pytestconfig.test_engine.dispose()


@pytest.fixture
def test_db(test_engine):
    """
    Function-scoped session with savepoint isolation.

    The service layer commits mid-test; the savepoint makes those commits
    reversible so every test starts from a clean database.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    # The session transaction becomes a SAVEPOINT inside the outer
    # transaction, so mid-test commits (service layer) only release the
    # savepoint; teardown rolls back everything.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(test_db):
    """FastAPI TestClient wired to the isolated test database"""
    from fastapi.testclient import TestClient

    from server.app import main as main_module
    from server.app.database import get_db
    from server.app.main import app

    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    # Tables already exist on the test engine (created in pytest_configure).
    # Disable the app's init_db so the lifespan doesn't open a competing
    # transaction on the shared StaticPool connection.
    original_init_db = main_module.init_db
    main_module.init_db = lambda: None

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        main_module.init_db = original_init_db
        app.dependency_overrides.clear()


# Pre-seeded fixtures
TEST_AGENT_TOKEN = "test-agent-token"


@pytest.fixture
def agent_token():
    """Bearer token of the agent created by the db_with_agent fixture"""
    return TEST_AGENT_TOKEN


@pytest.fixture
def db_with_agent(test_db):
    """Database session plus a registered test agent (with a bearer token)"""
    from server.app.models import Agent, HealthStatus
    from server.app.security import hash_token

    agent = Agent(
        agent_id="test-agent-1",
        hostname="test.local",
        ip_address="192.168.1.100",
        status=HealthStatus.UP,
        token_hash=hash_token(TEST_AGENT_TOKEN),
    )
    test_db.add(agent)
    test_db.commit()
    test_db.refresh(agent)

    return test_db, agent


@pytest.fixture
def db_with_system(db_with_agent):
    """Database session plus test agent and system"""
    from server.app.models import HealthStatus, System

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
