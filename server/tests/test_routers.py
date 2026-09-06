"""
Tests for Recur server API routes
"""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from server.app.database import Base, SessionLocal, engine, init_db
from server.app.main import app
from server.app.models import Agent, HealthStatus, System, Task


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Setup test database"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """FastAPI test client"""
    return TestClient(app)


@pytest.fixture
def db_session():
    """Database session fixture"""
    session = SessionLocal()
    yield session
    session.close()


class TestAgentRoutes:
    """Tests for agent management endpoints"""

    def test_register_agent(self, client):
        """Test agent registration"""
        response = client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "test-agent-1",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
                "agent_version": "0.1.0",
                "os_type": "Linux",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-agent-1"
        assert data["hostname"] == "test.local"
        assert data["status"] in ["UP", "DOWN", "UNKNOWN"]

    def test_register_agent_duplicate(self, client):
        """Test duplicate agent registration updates existing"""
        # Register first time
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "test-agent-dup",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )

        # Register again with updated info
        response = client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "test-agent-dup",
                "hostname": "test-updated.local",
                "ip_address": "192.168.1.101",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["hostname"] == "test-updated.local"

    def test_list_agents(self, client):
        """Test listing agents"""
        # Register an agent first
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "test-agent-list",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )

        response = client.get("/api/v1/agents")

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "total" in data
        assert data["total"] >= 1

    def test_list_agents_pagination(self, client):
        """Test agent pagination"""
        response = client.get("/api/v1/agents?skip=0&limit=5")

        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "total" in data
        assert len(data["agents"]) <= 5

    def test_get_agent(self, client):
        """Test getting specific agent"""
        # Register agent first
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "test-agent-get",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )

        response = client.get("/api/v1/agents/test-agent-get")

        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-agent-get"

    def test_get_nonexistent_agent(self, client):
        """Test getting nonexistent agent"""
        response = client.get("/api/v1/agents/nonexistent")
        assert response.status_code == 404

    def test_get_agent_systems(self, client):
        """Test getting systems for an agent"""
        # Register agent
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "test-agent-sys",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )

        response = client.get("/api/v1/agents/test-agent-sys/systems")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_agent_heartbeat(self, client):
        """Test agent heartbeat"""
        # Register agent first
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "test-agent-hb",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )

        response = client.put("/api/v1/agents/test-agent-hb/heartbeat")

        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-agent-hb"

    def test_delete_agent(self, client):
        """Test agent deletion"""
        # Register agent first
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "test-agent-del",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )

        response = client.delete("/api/v1/agents/test-agent-del")

        assert response.status_code == 200

        # Verify it's deleted
        response = client.get("/api/v1/agents/test-agent-del")
        assert response.status_code == 404


class TestSystemRoutes:
    """Tests for system management endpoints"""

    @pytest.fixture(autouse=True)
    def setup_agent(self, client):
        """Setup agent for system tests"""
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "system-test-agent",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )

    def test_create_system(self, client):
        """Test system creation"""
        response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "test-system",
                "name": "Test System",
                "description": "A test system",
                "agent_id": "system-test-agent",
                "config": {
                    "name": "Test",
                    "tasks": [
                        {
                            "name": "test-task",
                            "type": "http",
                            "url": "http://localhost/health",
                            "expected_status": 200,
                        }
                    ],
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["system_id"] == "test-system"
        assert data["name"] == "Test System"

    def test_create_system_invalid_config(self, client):
        """Test system creation with invalid config"""
        response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "bad-system",
                "name": "Bad System",
                "agent_id": "system-test-agent",
                "config": {
                    # Missing 'name' field
                    "tasks": []
                },
            },
        )

        assert response.status_code >= 400

    def test_list_systems(self, client):
        """Test listing systems"""
        # Create a system first
        client.post(
            "/api/v1/systems",
            json={
                "system_id": "test-system-list",
                "name": "Test System",
                "agent_id": "system-test-agent",
                "config": {
                    "name": "Test",
                    "tasks": [],
                },
            },
        )

        response = client.get("/api/v1/systems")

        assert response.status_code == 200
        data = response.json()
        assert "systems" in data
        assert "total" in data

    def test_list_systems_pagination(self, client):
        """Test system pagination"""
        response = client.get("/api/v1/systems?skip=0&limit=5")

        assert response.status_code == 200
        data = response.json()
        assert "systems" in data
        assert len(data["systems"]) <= 5

    def test_get_system(self, client):
        """Test getting specific system"""
        # Create system first
        client.post(
            "/api/v1/systems",
            json={
                "system_id": "test-system-get",
                "name": "Test System",
                "agent_id": "system-test-agent",
                "config": {
                    "name": "Test",
                    "tasks": [],
                },
            },
        )

        response = client.get("/api/v1/systems/test-system-get")

        assert response.status_code == 200
        data = response.json()
        assert data["system_id"] == "test-system-get"

    def test_get_nonexistent_system(self, client):
        """Test getting nonexistent system"""
        response = client.get("/api/v1/systems/nonexistent")
        assert response.status_code == 404

    def test_get_system_tree(self, client):
        """Test getting system dependency tree"""
        # Create system
        client.post(
            "/api/v1/systems",
            json={
                "system_id": "test-system-tree",
                "name": "Test System",
                "agent_id": "system-test-agent",
                "config": {
                    "name": "Test",
                    "tasks": [],
                },
            },
        )

        response = client.get("/api/v1/systems/test-system-tree/tree")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "status" in data

    def test_get_system_health(self, client):
        """Test getting system health summary"""
        # Create system
        client.post(
            "/api/v1/systems",
            json={
                "system_id": "test-system-health",
                "name": "Test System",
                "agent_id": "system-test-agent",
                "config": {
                    "name": "Test",
                    "tasks": [],
                },
            },
        )

        response = client.get("/api/v1/systems/test-system-health/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_update_system(self, client):
        """Test system update"""
        # Create system first
        client.post(
            "/api/v1/systems",
            json={
                "system_id": "test-system-update",
                "name": "Test System",
                "agent_id": "system-test-agent",
                "config": {
                    "name": "Test",
                    "tasks": [],
                },
            },
        )

        # Update it
        response = client.put(
            "/api/v1/systems/test-system-update",
            json={
                "name": "Updated Name",
                "config": {
                    "name": "Updated",
                    "tasks": [],
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"

    def test_delete_system(self, client):
        """Test system deletion"""
        # Create system first
        client.post(
            "/api/v1/systems",
            json={
                "system_id": "test-system-del",
                "name": "Test System",
                "agent_id": "system-test-agent",
                "config": {
                    "name": "Test",
                    "tasks": [],
                },
            },
        )

        response = client.delete("/api/v1/systems/test-system-del")

        assert response.status_code == 200

        # Verify deletion
        response = client.get("/api/v1/systems/test-system-del")
        assert response.status_code == 404


class TestStatusRoutes:
    """Tests for status reporting endpoints"""

    @pytest.fixture(autouse=True)
    def setup_data(self, client):
        """Setup agent and system for tests"""
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "status-test-agent",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )

        client.post(
            "/api/v1/systems",
            json={
                "system_id": "status-test-system",
                "name": "Test System",
                "agent_id": "status-test-agent",
                "config": {
                    "name": "Test",
                    "tasks": [],
                },
            },
        )

    def test_submit_status_report(self, client):
        """Test status report submission"""
        response = client.post(
            "/api/v1/status",
            json={
                "agent_id": "status-test-agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system_status": {
                    "system_id": "status-test-system",
                    "name": "Test",
                    "status": "UP",
                    "tasks": [],
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"

    def test_submit_status_report_unknown_agent(self, client):
        """Test status report with unknown agent"""
        response = client.post(
            "/api/v1/status",
            json={
                "agent_id": "unknown-agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system_status": {
                    "system_id": "status-test-system",
                    "name": "Test",
                    "status": "UP",
                    "tasks": [],
                },
            },
        )

        assert response.status_code >= 400

    def test_health_check(self, client):
        """Test server health check"""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_get_system_history(self, client):
        """Test getting system status history"""
        # Submit a status report first
        client.post(
            "/api/v1/status",
            json={
                "agent_id": "status-test-agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system_status": {
                    "system_id": "status-test-system",
                    "name": "Test",
                    "status": "UP",
                    "tasks": [],
                },
            },
        )

        response = client.get(
            "/api/v1/systems/status-test-system/history?limit=10"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestErrorHandling:
    """Tests for error handling and edge cases"""

    def test_invalid_json(self, client):
        """Test handling of invalid JSON"""
        response = client.post(
            "/api/v1/agents/register",
            data="invalid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code >= 400

    def test_missing_required_fields(self, client):
        """Test missing required fields in request"""
        response = client.post(
            "/api/v1/agents/register",
            json={"agent_id": "test"},  # Missing hostname and ip_address
        )

        assert response.status_code >= 400

    def test_invalid_task_type(self, client):
        """Test invalid task type in system config"""
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "error-test-agent",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )

        response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "bad-task-system",
                "name": "Bad System",
                "agent_id": "error-test-agent",
                "config": {
                    "name": "Test",
                    "tasks": [
                        {
                            "name": "bad-task",
                            "type": "invalid_type",
                        }
                    ],
                },
            },
        )

        assert response.status_code >= 400
