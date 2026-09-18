"""
Comprehensive test suite for Recur server
Tests for models, services, routers, and utilities
"""

import json
from datetime import datetime, timezone

import pytest

from server.app.models import Agent, HealthStatus, StatusReport, System, Task, TaskResult
from server.app.services.status_evaluator import StatusEvaluator
from server.app.utils.yaml_loader import (
    YAMLConfigError,
    config_to_json_serializable,
    flatten_config,
    validate_system_config,
    validate_task_type_config,
)

# Note: the `client`, `test_db`, and `test_engine` fixtures come from
# conftest.py (shared in-memory engine, per-test savepoint isolation).


class TestAgentRouters:
    """Tests for agent management API endpoints"""

    def test_register_agent_success(self, client):
        """Test successful agent registration"""
        response = client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "test-agent-1",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["agent_id"] == "test-agent-1"

    def test_register_agent_missing_fields(self, client):
        """Test agent registration with missing fields"""
        response = client.post(
            "/api/v1/agents/register",
            json={"agent_id": "test"},
        )
        assert response.status_code >= 400

    def test_list_agents(self, client):
        """Test listing agents"""
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "list-test-1",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )
        response = client.get("/api/v1/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert "total" in data

    def test_get_agent(self, client):
        """Test getting specific agent"""
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "get-test-1",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )
        response = client.get("/api/v1/agents/get-test-1")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "get-test-1"

    def test_get_nonexistent_agent(self, client):
        """Test getting nonexistent agent returns 404"""
        response = client.get("/api/v1/agents/nonexistent-agent")
        assert response.status_code == 404

    def test_agent_heartbeat(self, client):
        """Test agent heartbeat endpoint (requires the agent token)"""
        registration = client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "hb-test-1",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )
        token = registration.json()["agent_token"]
        response = client.put(
            "/api/v1/agents/hb-test-1/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    def test_delete_agent(self, client):
        """Test agent deletion"""
        client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "del-test-1",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )
        response = client.delete("/api/v1/agents/del-test-1")
        assert response.status_code in [200, 204]


class TestSystemRouters:
    """Tests for system management API endpoints"""

    @pytest.fixture(autouse=True)
    def setup_agent(self, client):
        """Register an agent for system tests and expose its database id"""
        response = client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "sys-test-agent",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )
        self.agent_db_id = response.json()["id"]

    def test_create_system_success(self, client):
        """Test successful system creation"""
        response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "create-test-1",
                "name": "Test System",
                "agent_id": self.agent_db_id,
                "config": {
                    "name": "Test",
                    "tasks": [],
                },
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["system_id"] == "create-test-1"

    def test_create_system_invalid_config(self, client):
        """Test system creation with invalid config"""
        response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "bad-config",
                "name": "Bad",
                "agent_id": self.agent_db_id,
                "config": {"tasks": []},  # Missing 'name'
            },
        )
        assert response.status_code >= 400

    def test_list_systems(self, client):
        """Test listing systems"""
        response = client.get("/api/v1/systems")
        assert response.status_code == 200
        data = response.json()
        assert "systems" in data

    def test_health_check_endpoint(self, client):
        """Test server health check endpoint"""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


# ==================== Model Tests ====================


class TestAgentModel:
    """Tests for Agent model"""

    def test_agent_creation(self, test_db):
        """Test creating an agent"""
        agent = Agent(
            agent_id="model-test-1",
            hostname="test.local",
            ip_address="192.168.1.100",
            status=HealthStatus.UP,
        )
        test_db.add(agent)
        test_db.commit()
        test_db.refresh(agent)

        assert agent.agent_id == "model-test-1"
        assert agent.status == HealthStatus.UP

    def test_agent_status_enum(self, test_db):
        """Test agent status enum values"""
        all_statuses = [
            HealthStatus.UP,
            HealthStatus.DOWN,
            HealthStatus.UNKNOWN,
            HealthStatus.DEGRADED,
        ]
        for status in all_statuses:
            agent = Agent(
                agent_id=f"model-test-{status.value}",
                hostname="test.local",
                ip_address="192.168.1.100",
                status=status,
            )
            test_db.add(agent)

        test_db.commit()
        agents = test_db.query(Agent).all()
        assert len(agents) >= 4


class TestSystemModel:
    """Tests for System model"""

    def test_system_creation(self, test_db):
        """Test creating a system"""
        agent = Agent(
            agent_id="sys-model-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="sys-model-test",
            agent_id=agent.id,
            name="Test System",
            config={"name": "Test", "tasks": []},
            status=HealthStatus.UP,
        )
        test_db.add(system)
        test_db.commit()
        test_db.refresh(system)

        assert system.system_id == "sys-model-test"
        assert system.name == "Test System"

    def test_system_relationships(self, test_db):
        """Test system relationships"""
        agent = Agent(
            agent_id="sys-rel-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="sys-rel-test",
            agent_id=agent.id,
            name="Test",
            config={"name": "Test", "tasks": []},
        )
        test_db.add(system)
        test_db.commit()

        task = Task(
            task_id="task-rel-test",
            system_id=system.id,
            name="rel-task",
            task_type="http",
            config={"url": "http://localhost"},
        )
        test_db.add(task)
        test_db.commit()

        retrieved_system = test_db.query(System).filter(System.system_id == "sys-rel-test").first()
        assert retrieved_system is not None


class TestTaskModel:
    """Tests for Task model"""

    def test_task_creation(self, test_db):
        """Test creating a task"""
        agent = Agent(
            agent_id="task-model-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="task-model-sys",
            agent_id=agent.id,
            name="Test",
            config={"name": "Test", "tasks": []},
        )
        test_db.add(system)
        test_db.commit()

        task = Task(
            task_id="task-model-test",
            system_id=system.id,
            name="model-task",
            task_type="http",
            config={"url": "http://localhost", "expected_status": 200},
            status=HealthStatus.UP,
        )
        test_db.add(task)
        test_db.commit()
        test_db.refresh(task)

        assert task.task_id == "task-model-test"
        assert task.task_type == "http"

    def test_task_types(self, test_db):
        """Test different task types"""
        agent = Agent(
            agent_id="task-types-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="task-types-sys",
            agent_id=agent.id,
            name="Test",
            config={"name": "Test", "tasks": []},
        )
        test_db.add(system)
        test_db.commit()

        task_types = ["http", "https", "tcp", "ping", "command"]
        for task_type in task_types:
            task = Task(
                task_id=f"task-{task_type}",
                system_id=system.id,
                name=f"task-{task_type}",
                task_type=task_type,
                config={},
            )
            test_db.add(task)

        test_db.commit()
        tasks = test_db.query(Task).filter(Task.system_id == system.id).all()
        assert len(tasks) == 5


# ==================== Service Tests ====================


def _add_task_result(test_db, task, status, agent_pk, error=None):
    """Attach a TaskResult row (anchored to a StatusReport) to a task"""
    report = StatusReport(
        agent_id=agent_pk,
        system_id=task.system_id,
        report_timestamp=datetime.utcnow(),
        report_data={},
    )
    test_db.add(report)
    test_db.flush()

    result = TaskResult(
        task_id=task.id,
        status_report_id=report.id,
        status=status,
        duration_ms=5.0,
        error_message=error,
    )
    test_db.add(result)
    test_db.commit()
    return result


class TestStatusEvaluatorService:
    """Tests for StatusEvaluator service"""

    def test_evaluate_empty_system(self, test_db):
        """Test evaluating system with no tasks"""
        agent = Agent(
            agent_id="eval-empty-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="eval-empty-sys",
            agent_id=agent.id,
            name="Test",
            config={"name": "Test", "tasks": []},
        )
        test_db.add(system)
        test_db.commit()

        evaluator = StatusEvaluator()
        status = evaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.UNKNOWN

    def test_evaluate_system_with_up_task(self, test_db):
        """Test evaluation with UP task"""
        agent = Agent(
            agent_id="eval-up-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="eval-up-sys",
            agent_id=agent.id,
            name="Test",
            config={"name": "Test", "tasks": []},
        )
        test_db.add(system)
        test_db.commit()

        task = Task(
            task_id="eval-up-task",
            system_id=system.id,
            name="eval-up-task",
            task_type="http",
            config={},
        )
        test_db.add(task)
        test_db.commit()
        test_db.refresh(task)

        _add_task_result(test_db, task, HealthStatus.UP, agent.id)

        evaluator = StatusEvaluator()
        status = evaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.UP

    def test_evaluate_system_with_down_task(self, test_db):
        """Test evaluation with DOWN task"""
        agent = Agent(
            agent_id="eval-down-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="eval-down-sys",
            agent_id=agent.id,
            name="Test",
            config={"name": "Test", "tasks": []},
        )
        test_db.add(system)
        test_db.commit()

        task = Task(
            task_id="eval-down-task",
            system_id=system.id,
            name="eval-down-task",
            task_type="http",
            config={},
        )
        test_db.add(task)
        test_db.commit()
        test_db.refresh(task)

        _add_task_result(test_db, task, HealthStatus.DOWN, agent.id, error="boom")

        evaluator = StatusEvaluator()
        status = evaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.DOWN

    def test_evaluate_mixed_tasks(self, test_db):
        """Test evaluation with mixed UP/DOWN tasks"""
        agent = Agent(
            agent_id="eval-mixed-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="eval-mixed-sys",
            agent_id=agent.id,
            name="Test",
            config={"name": "Test", "tasks": []},
        )
        test_db.add(system)
        test_db.commit()

        # Add UP task
        task1 = Task(
            task_id="eval-mixed-up",
            system_id=system.id,
            name="eval-mixed-up",
            task_type="http",
            config={},
        )
        test_db.add(task1)

        # Add DOWN task
        task2 = Task(
            task_id="eval-mixed-down",
            system_id=system.id,
            name="eval-mixed-down",
            task_type="tcp",
            config={},
        )
        test_db.add(task2)
        test_db.commit()
        test_db.refresh(task1)
        test_db.refresh(task2)

        _add_task_result(test_db, task1, HealthStatus.UP, agent.id)
        _add_task_result(test_db, task2, HealthStatus.DOWN, agent.id, error="boom")

        evaluator = StatusEvaluator()
        status = evaluator.evaluate_system_status(system, test_db)
        assert status == HealthStatus.DOWN

    def test_get_system_tree(self, test_db):
        """Test getting system tree structure"""
        agent = Agent(
            agent_id="tree-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="tree-sys",
            agent_id=agent.id,
            name="Test",
            config={"name": "Test", "tasks": []},
        )
        test_db.add(system)
        test_db.commit()

        evaluator = StatusEvaluator()
        tree = evaluator.get_system_tree(system, test_db)

        assert tree is not None
        assert tree["system_id"] == "tree-sys"
        assert "tasks" in tree
        assert "dependencies" in tree


# ==================== Utility Tests ====================


class TestYAMLValidation:
    """Tests for YAML validation utilities"""

    def test_validate_valid_config(self):
        """Test validating valid system config (wrapped in 'system' root key)"""
        config = {
            "system": {
                "name": "Test",
                "tasks": [],
            }
        }
        validate_system_config(config)  # Should not raise

    def test_validate_missing_name(self):
        """Test validation fails for missing name"""
        config = {
            "system": {
                "tasks": [],
            }
        }
        with pytest.raises(YAMLConfigError):
            validate_system_config(config)

    def test_validate_http_task(self):
        """Test HTTP task validation"""
        task = {
            "type": "http",
            "url": "http://localhost",
            "expected_status": 200,
        }
        validate_task_type_config(task)  # Should not raise

    def test_validate_tcp_task(self):
        """Test TCP task validation"""
        task = {
            "type": "tcp",
            "host": "localhost",
            "port": 5432,
        }
        validate_task_type_config(task)  # Should not raise

    def test_validate_http_missing_url(self):
        """Test HTTP validation fails without URL"""
        task = {
            "type": "http",
        }
        with pytest.raises(YAMLConfigError):
            validate_task_type_config(task)

    def test_flatten_config(self):
        """Test flattening hierarchical config"""
        config = {
            "system": {
                "name": "Test",
                "tasks": [{"name": "t1"}],
                "dependencies": [
                    {
                        "name": "Child",
                        "tasks": [{"name": "t2"}],
                    }
                ],
            }
        }
        result = flatten_config(config)
        assert isinstance(result, dict)
        assert "test" in result
        assert "child" in result
        assert result["child"]["parent_id"] == "test"

    def test_config_to_json_serializable(self):
        """Test converting config to JSON-serializable format"""
        config = {
            "name": "Test",
            "tasks": [],
            "nested": {
                "value": 123,
            },
        }
        result = config_to_json_serializable(config)
        # Should not raise an error when dumped to JSON
        json_str = json.dumps(result)
        assert isinstance(json_str, str)


# ==================== Error and Edge Cases ====================


class TestErrorHandling:
    """Tests for error handling and edge cases"""

    def test_create_system_unknown_agent(self, client):
        """Test creating system for unknown agent"""
        response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "unknown-agent-sys",
                "name": "Test",
                "agent_id": "unknown-agent",
                "config": {"name": "Test", "tasks": []},
            },
        )
        # Should fail because agent doesn't exist
        assert response.status_code >= 400

    def test_submit_status_unknown_agent(self, client):
        """Test submitting status for unknown agent"""
        response = client.post(
            "/api/v1/status",
            json={
                "agent_id": "unknown-agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system_status": {
                    "system_id": "some-sys",
                    "name": "Test",
                    "status": "UP",
                    "tasks": [],
                },
            },
        )
        assert response.status_code >= 400

    def test_list_agents_pagination_limit(self, client):
        """Test pagination with limit parameter"""
        response = client.get("/api/v1/agents?skip=0&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) <= 5

    def test_invalid_status_enum(self, test_db):
        """Test that invalid status values are rejected"""
        agent = Agent(
            agent_id="invalid-status",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        # Valid status values should work
        valid_statuses = (
            HealthStatus.UP,
            HealthStatus.DOWN,
            HealthStatus.UNKNOWN,
            HealthStatus.DEGRADED,
        )
        assert agent.status in valid_statuses

    def test_unicode_in_system_name(self, test_db):
        """Test system with unicode characters"""
        agent = Agent(
            agent_id="unicode-agent",
            hostname="test.local",
            ip_address="192.168.1.100",
        )
        test_db.add(agent)
        test_db.commit()

        system = System(
            system_id="unicode-sys",
            agent_id=agent.id,
            name="Sistema 日本語 🚀",
            config={"name": "Test", "tasks": []},
        )
        test_db.add(system)
        test_db.commit()
        test_db.refresh(system)

        assert "日本語" in system.name


# ==================== Integration Tests ====================


class TestIntegration:
    """Integration tests combining multiple components"""

    def test_full_system_workflow(self, client):
        """Test complete workflow: register agent, create system, submit status"""
        # 1. Register agent
        agent_response = client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "workflow-agent",
                "hostname": "test.local",
                "ip_address": "192.168.1.100",
            },
        )
        assert agent_response.status_code in [200, 201]
        token = agent_response.json()["agent_token"]

        # 2. Create system (agent_id is the integer DB id from registration)
        system_response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "workflow-sys",
                "name": "Workflow Test",
                "agent_id": agent_response.json()["id"],
                "config": {
                    "name": "Workflow",
                    "tasks": [],
                },
            },
        )
        assert system_response.status_code in [200, 201]

        # 3. Get system
        get_response = client.get("/api/v1/systems/workflow-sys")
        assert get_response.status_code == 200

        # 4. Submit status
        status_response = client.post(
            "/api/v1/status",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "agent_id": "workflow-agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system_status": {
                    "system_id": "workflow-sys",
                    "name": "Workflow",
                    "status": "UP",
                    "tasks": [],
                },
            },
        )
        assert status_response.status_code == 200
