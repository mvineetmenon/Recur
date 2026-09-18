"""
Tests for Recur server API routes
"""

from datetime import datetime, timezone

import pytest


def _register_agent(client, agent_id, hostname="test.local"):
    """Register an agent and return the response (201)"""
    return client.post(
        "/api/v1/agents/register",
        json={
            "agent_id": agent_id,
            "hostname": hostname,
            "ip_address": "192.168.1.100",
            "version": "0.1.0",
            "os_type": "Linux",
        },
    )


def _token(response):
    """Bearer token issued to the agent by a first registration"""
    return response.json()["agent_token"]


def _auth(token):
    """Authorization headers for an agent token"""
    return {"Authorization": f"Bearer {token}"}


class TestAgentRoutes:
    """Tests for agent management endpoints"""

    def test_register_agent(self, client):
        """Test agent registration returns 201 with agent payload"""
        response = _register_agent(client, "test-agent-1")

        assert response.status_code == 201
        data = response.json()
        assert data["agent_id"] == "test-agent-1"
        assert data["hostname"] == "test.local"
        assert data["status"] in ["UP", "DOWN", "UNKNOWN"]

    def test_register_agent_duplicate_updates(self, client):
        """Test duplicate agent registration updates existing"""
        _register_agent(client, "test-agent-dup")

        response = _register_agent(client, "test-agent-dup", hostname="test-updated.local")

        assert response.status_code == 201
        data = response.json()
        assert data["hostname"] == "test-updated.local"

    def test_list_agents(self, client):
        """Test listing agents"""
        _register_agent(client, "test-agent-list")

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
        _register_agent(client, "test-agent-get")

        response = client.get("/api/v1/agents/test-agent-get")

        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-agent-get"

    def test_get_nonexistent_agent(self, client):
        """Test getting nonexistent agent returns 404"""
        response = client.get("/api/v1/agents/nonexistent")
        assert response.status_code == 404

    def test_get_agent_systems(self, client):
        """Test getting systems for an agent (returns a dict)"""
        _register_agent(client, "test-agent-sys")

        response = client.get("/api/v1/agents/test-agent-sys/systems")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert data["agent_id"] == "test-agent-sys"
        assert data["system_count"] == 0
        assert data["systems"] == []

    def test_agent_heartbeat(self, client):
        """Test agent heartbeat with a valid token"""
        registration = _register_agent(client, "test-agent-hb")
        token = _token(registration)

        response = client.put("/api/v1/agents/test-agent-hb/heartbeat", headers=_auth(token))

        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-agent-hb"

    def test_heartbeat_unknown_agent(self, client):
        """Test heartbeat without a token returns 401"""
        response = client.put("/api/v1/agents/ghost/heartbeat")
        assert response.status_code == 401

    def test_heartbeat_invalid_token(self, client):
        """Test heartbeat with an unknown token returns 401"""
        response = client.put("/api/v1/agents/ghost/heartbeat", headers=_auth("not-a-real-token"))
        assert response.status_code == 401

    def test_heartbeat_token_agent_mismatch(self, client):
        """Test heartbeat with another agent's token returns 403"""
        registration = _register_agent(client, "test-agent-hb-other")
        token = _token(registration)

        response = client.put("/api/v1/agents/someone-else/heartbeat", headers=_auth(token))
        assert response.status_code == 403

    def test_register_reregistration_rotates_token(self, client):
        """First registration issues a token; re-registration rotates it and
        returns the new plaintext (recovery path for lost token files)."""
        first = _register_agent(client, "test-agent-rotate")
        assert first.status_code == 201
        token = _token(first)
        assert token

        again = _register_agent(client, "test-agent-rotate")
        assert again.status_code == 201
        new_token = again.json()["agent_token"]
        assert new_token and new_token != token

        # the old token is no longer valid
        old = client.put("/api/v1/agents/test-agent-rotate/heartbeat", headers=_auth(token))
        assert old.status_code == 401
        # the rotated token works
        ok = client.put("/api/v1/agents/test-agent-rotate/heartbeat", headers=_auth(new_token))
        assert ok.status_code == 200

    def test_register_requires_enrollment_when_configured(self, client, monkeypatch):
        """With RECUR_ENROLLMENT_TOKEN set, new registrations need the enrollment
        token (or an existing agent token); without it they get 401."""
        from server.app import config

        monkeypatch.setattr(config, "ENROLLMENT_TOKEN", "enroll-secret")

        response = _register_agent(client, "test-agent-enrolled")
        assert response.status_code == 401

        response = client.post(
            "/api/v1/agents/register",
            headers={"X-Recur-Enrollment-Token": "enroll-secret"},
            json={
                "agent_id": "test-agent-enrolled",
                "hostname": "enroll.local",
                "ip_address": "192.168.1.100",
            },
        )
        assert response.status_code == 201
        assert response.json()["agent_token"]

    def test_register_open_enrollment_issues_token(self, client):
        """Without an enrollment token configured, registration is open and
        still issues a per-agent token."""
        response = _register_agent(client, "test-agent-open")
        assert response.status_code == 201
        assert response.json()["agent_token"]

    def test_delete_agent(self, client):
        """Test agent deletion returns 204 and removes the agent"""
        _register_agent(client, "test-agent-del")

        response = client.delete("/api/v1/agents/test-agent-del")

        assert response.status_code == 204

        response = client.get("/api/v1/agents/test-agent-del")
        assert response.status_code == 404

    def test_delete_agent_with_reports(self, client):
        """Deleting an agent that already submitted reports succeeds (204)

        Regression: the non-nullable status_reports.agent_id FK used to make
        the delete fail with a 500 IntegrityError.
        """
        registration = _register_agent(client, "test-agent-del-reports")
        agent_db_id = registration.json()["id"]
        token = _token(registration)

        system = client.post(
            "/api/v1/systems",
            json={
                "system_id": "del-report-sys",
                "name": "Del Report Sys",
                "agent_id": agent_db_id,
                "config": {
                    "name": "Del Report Sys",
                    "tasks": [{"name": "t1", "type": "http", "url": "http://x"}],
                },
            },
        )
        assert system.status_code == 201

        report = client.post(
            "/api/v1/status",
            headers=_auth(token),
            json={
                "agent_id": "test-agent-del-reports",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system_status": {
                    "system_id": "del-report-sys",
                    "name": "Del Report Sys",
                    "status": "UP",
                    "tasks": [{"task_id": "t1", "name": "t1", "type": "http", "status": "UP"}],
                },
            },
        )
        assert report.status_code == 200

        response = client.delete("/api/v1/agents/test-agent-del-reports")
        assert response.status_code == 204
        assert client.get("/api/v1/agents/test-agent-del-reports").status_code == 404

        # The system survives with its agent FK nullified; history is gone
        system_after = client.get("/api/v1/systems/del-report-sys")
        assert system_after.status_code == 200
        assert system_after.json()["agent_id"] is None
        assert client.get("/api/v1/systems/del-report-sys/history").status_code == 404


class TestSystemRoutes:
    """Tests for system management endpoints"""

    @pytest.fixture(autouse=True)
    def setup_agent(self, client):
        """Register an agent and expose its database id"""
        response = _register_agent(client, "system-test-agent")
        assert response.status_code == 201
        self.agent_db_id = response.json()["id"]

    def _create_payload(self, system_id, **overrides):
        payload = {
            "system_id": system_id,
            "name": "Test System",
            "config": {"name": "Test", "tasks": []},
            "agent_id": self.agent_db_id,
        }
        payload.update(overrides)
        return payload

    def test_create_system(self, client):
        """Test system creation returns 201"""
        response = client.post(
            "/api/v1/systems",
            json=self._create_payload(
                "test-system",
                config={
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
            ),
        )

        assert response.status_code == 201
        data = response.json()
        assert data["system_id"] == "test-system"
        assert data["name"] == "Test System"
        assert data["agent_id"] == self.agent_db_id

    def test_create_system_unknown_agent(self, client):
        """Test creating system for nonexistent agent fails"""
        response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "bad-agent-sys",
                "name": "Bad Agent System",
                "config": {"name": "Test", "tasks": []},
                "agent_id": 999999,
            },
        )
        assert response.status_code >= 400

    def test_create_system_invalid_config(self, client):
        """Test system creation with invalid config (missing name)"""
        response = client.post(
            "/api/v1/systems",
            json=self._create_payload("bad-system", config={"tasks": []}),
        )

        assert response.status_code == 400

    def test_list_systems(self, client):
        """Test listing systems"""
        client.post("/api/v1/systems", json=self._create_payload("test-system-list"))

        response = client.get("/api/v1/systems")

        assert response.status_code == 200
        data = response.json()
        assert "systems" in data
        assert "total" in data
        assert data["total"] >= 1

    def test_list_systems_pagination(self, client):
        """Test system pagination"""
        response = client.get("/api/v1/systems?skip=0&limit=5")

        assert response.status_code == 200
        data = response.json()
        assert "systems" in data
        assert len(data["systems"]) <= 5

    def test_get_system(self, client):
        """Test getting specific system"""
        client.post("/api/v1/systems", json=self._create_payload("test-system-get"))

        response = client.get("/api/v1/systems/test-system-get")

        assert response.status_code == 200
        data = response.json()
        assert data["system_id"] == "test-system-get"

    def test_get_nonexistent_system(self, client):
        """Test getting nonexistent system returns 404"""
        response = client.get("/api/v1/systems/nonexistent")
        assert response.status_code == 404

    def test_create_system_with_nested_dependencies(self, client):
        """Test nested dependencies are registered as child systems"""
        response = client.post(
            "/api/v1/systems",
            json=self._create_payload(
                "nested-parent",
                config={
                    "name": "Parent",
                    "tasks": [{"name": "p-task", "type": "http", "url": "http://x"}],
                    "dependencies": [
                        {
                            "name": "Child",
                            "tasks": [{"name": "c-task", "type": "tcp", "host": "x", "port": 1}],
                        }
                    ],
                },
            ),
        )
        assert response.status_code == 201

        tree = client.get("/api/v1/systems/nested-parent/tree")
        assert tree.status_code == 200
        tree_data = tree.json()
        assert len(tree_data["dependencies"]) == 1
        child = tree_data["dependencies"][0]
        assert child["system_id"] == "nested-parent/child"
        assert child["name"] == "Child"
        assert len(child["dependencies"]) == 0

    def test_get_system_tree(self, client):
        """Test getting system dependency tree"""
        client.post("/api/v1/systems", json=self._create_payload("test-system-tree"))

        response = client.get("/api/v1/systems/test-system-tree/tree")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "status" in data
        assert "tasks" in data
        assert "dependencies" in data

    def test_system_forest_empty(self, client):
        """Test forest endpoint with no systems returns empty roots"""
        response = client.get("/api/v1/systems/forest")

        assert response.status_code == 200
        data = response.json()
        assert data["root_count"] == 0
        assert data["roots"] == []

    def test_system_forest_returns_roots_only_with_nested_tree(self, client):
        """Test forest lists only root systems, with children nested inside"""
        client.post(
            "/api/v1/systems",
            json=self._create_payload(
                "forest-parent",
                config={
                    "name": "Parent",
                    "tasks": [{"name": "p-task", "type": "http", "url": "http://x"}],
                    "dependencies": [
                        {
                            "name": "Child",
                            "tasks": [{"name": "c-task", "type": "tcp", "host": "x", "port": 1}],
                        }
                    ],
                },
            ),
        )
        # Independent second root
        client.post("/api/v1/systems", json=self._create_payload("forest-other"))

        response = client.get("/api/v1/systems/forest")
        assert response.status_code == 200
        data = response.json()

        # Only roots at top level (child is nested, not a root)
        assert data["root_count"] == 2
        root_ids = {root["system_id"] for root in data["roots"]}
        assert root_ids == {"forest-parent", "forest-other"}

        parent = next(r for r in data["roots"] if r["system_id"] == "forest-parent")
        assert len(parent["tasks"]) == 1
        assert parent["tasks"][0]["task_id"] == "p-task"
        assert len(parent["dependencies"]) == 1
        child = parent["dependencies"][0]
        assert child["system_id"] == "forest-parent/child"
        assert child["name"] == "Child"
        assert len(child["dependencies"]) == 0
        assert child["tasks"][0]["task_id"] == "c-task"

    def test_system_forest_shared_dependency(self, client, test_db):
        """Test a child shared by several parents renders once per path (diamond)"""
        from server.app.models import System, SystemDependency, Task

        a = System(system_id="dia-a", name="A", config={"name": "A", "tasks": []})
        b = System(system_id="dia-b", name="B", config={"name": "B", "tasks": []})
        c = System(system_id="dia-c", name="C", config={"name": "C", "tasks": []})
        d = System(system_id="dia-d", name="D", config={"name": "D", "tasks": []})
        test_db.add_all([a, b, c, d])
        test_db.flush()

        test_db.add(
            Task(
                task_id="dia-d-task",
                system_id=d.id,
                name="d-task",
                task_type="tcp",
                config={"host": "x", "port": 1},
            )
        )
        for parent, child in ((a, b), (a, c), (b, d), (c, d)):
            test_db.add(
                SystemDependency(
                    parent_system_id=parent.id,
                    child_system_id=child.id,
                    criticality="HIGH",
                )
            )
        test_db.commit()

        response = client.get("/api/v1/systems/forest")
        assert response.status_code == 200
        data = response.json()

        # Only A is a root; the shared child D appears under both B and C
        assert data["root_count"] == 1
        root = data["roots"][0]
        assert root["system_id"] == "dia-a"
        assert [dep["system_id"] for dep in root["dependencies"]] == ["dia-b", "dia-c"]
        for dep in root["dependencies"]:
            shared = dep["dependencies"]
            assert [x["system_id"] for x in shared] == ["dia-d"]
            assert shared[0]["tasks"][0]["task_id"] == "dia-d-task"

    def test_get_system_health(self, client):
        """Test getting system health summary"""
        client.post("/api/v1/systems", json=self._create_payload("test-system-health"))

        response = client.get("/api/v1/systems/test-system-health/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "task_count" in data

    def test_update_system(self, client):
        """Test partial system update via PUT"""
        client.post("/api/v1/systems", json=self._create_payload("test-system-update"))

        response = client.put(
            "/api/v1/systems/test-system-update",
            json={
                "name": "Updated Name",
                "config": {"name": "Updated", "tasks": []},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"

    def test_update_system_name_only(self, client):
        """Test name-only update leaves config intact"""
        client.post(
            "/api/v1/systems",
            json=self._create_payload(
                "test-system-partial",
                config={
                    "name": "Orig",
                    "tasks": [{"name": "t", "type": "http", "url": "http://x"}],
                },
            ),
        )

        response = client.put(
            "/api/v1/systems/test-system-partial",
            json={"name": "Only Renamed"},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Only Renamed"

        tree = client.get("/api/v1/systems/test-system-partial/tree")
        assert tree.json()["tasks"][0]["name"] == "t"

    def test_update_nonexistent_system(self, client):
        """Test updating unknown system returns 404"""
        response = client.put("/api/v1/systems/ghost", json={"name": "X"})
        assert response.status_code == 404

    def test_delete_system(self, client):
        """Test system deletion returns 204 and removes the system"""
        client.post("/api/v1/systems", json=self._create_payload("test-system-del"))

        response = client.delete("/api/v1/systems/test-system-del")

        assert response.status_code == 204

        response = client.get("/api/v1/systems/test-system-del")
        assert response.status_code == 404


class TestStatusRoutes:
    """Tests for status reporting endpoints"""

    @pytest.fixture(autouse=True)
    def setup_data(self, client):
        """Setup agent and system for tests"""
        agent = _register_agent(client, "status-test-agent")
        assert agent.status_code == 201
        self.agent_db_id = agent.json()["id"]
        self.token = _token(agent)

        system = client.post(
            "/api/v1/systems",
            json={
                "system_id": "status-test-system",
                "name": "Test System",
                "agent_id": self.agent_db_id,
                "config": {
                    "name": "Test",
                    "tasks": [
                        {
                            "name": "s-task",
                            "type": "http",
                            "url": "http://x",
                            "expected_status": 200,
                        }
                    ],
                },
            },
        )
        assert system.status_code == 201

    def _report(self, agent_id="status-test-agent", tasks=None):
        return {
            "agent_id": agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system_status": {
                "system_id": "status-test-system",
                "name": "Test",
                "status": "UP",
                "tasks": tasks if tasks is not None else [],
            },
        }

    def _post_report(self, client, payload):
        return client.post("/api/v1/status", json=payload, headers=_auth(self.token))

    def test_submit_status_report(self, client):
        """Test status report submission is accepted"""
        response = self._post_report(client, self._report())

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "accepted"
        assert "report_id" in data

    def test_submit_status_report_requires_token(self, client):
        """Test status report without a token returns 401"""
        response = client.post("/api/v1/status", json=self._report())
        assert response.status_code == 401

    def test_submit_status_report_with_tasks(self, client):
        """Test task results are recorded and reflected in the system"""
        response = self._post_report(
            client,
            self._report(
                tasks=[
                    {
                        "task_id": "s-task",
                        "name": "s-task",
                        "type": "http",
                        "status": "UP",
                        "duration_ms": 12.0,
                        "error": None,
                    }
                ]
            ),
        )
        assert response.status_code == 200

        system = client.get("/api/v1/systems/status-test-system")
        assert system.status_code == 200
        assert system.json()["status"] == "UP"

    def test_submit_status_report_down_task(self, client):
        """Test a DOWN task rolls the system status down"""
        self._post_report(
            client,
            self._report(
                tasks=[
                    {
                        "task_id": "s-task",
                        "name": "s-task",
                        "type": "http",
                        "status": "DOWN",
                        "duration_ms": 12.0,
                        "error": "HTTP 500",
                    }
                ]
            ),
        )

        system = client.get("/api/v1/systems/status-test-system")
        assert system.json()["status"] == "DOWN"

    def test_submit_status_report_agent_mismatch(self, client):
        """Test a report claiming another agent's id is rejected (403)"""
        response = self._post_report(client, self._report(agent_id="unknown-agent"))
        assert response.status_code == 403

    def test_submit_status_report_unknown_system_auto_registers(self, client):
        """Test first report for an unknown system registers it (200)"""
        payload = self._report()
        payload["system_status"]["system_id"] = "no-such-system"
        response = self._post_report(client, payload)
        assert response.status_code == 200
        assert client.get("/api/v1/systems/no-such-system").status_code == 200

    def test_submit_status_report_missing_system_id(self, client):
        """A report with neither system_id nor name is rejected (400)"""
        response = client.post(
            "/api/v1/status",
            headers=_auth(self.token),
            json={
                "agent_id": "status-test-agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "system_status": {"tasks": []},
            },
        )
        assert response.status_code == 400

    def test_health_check(self, client):
        """Test server health check"""
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_get_system_history(self, client):
        """Test getting system status history (returns a dict)"""
        self._post_report(client, self._report())

        response = client.get("/api/v1/systems/status-test-system/history?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert data["system_id"] == "status-test-system"
        assert data["count"] >= 1
        assert isinstance(data["history"], list)

    def test_get_system_history_empty(self, client):
        """Test history for a system with no reports returns 404"""
        response = client.get("/api/v1/systems/status-test-system/history")
        assert response.status_code == 404


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
            json={"agent_id": "test"},
        )

        assert response.status_code == 422

    def test_invalid_task_type(self, client):
        """Test invalid task type in system config"""
        agent = _register_agent(client, "error-test-agent")
        agent_db_id = agent.json()["id"]

        response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "bad-task-system",
                "name": "Bad System",
                "agent_id": agent_db_id,
                "config": {
                    "name": "Test",
                    "tasks": [{"name": "bad-task", "type": "invalid_type"}],
                },
            },
        )

        assert response.status_code == 400


class TestDashboardRoutes:
    """Tests for the web UI routes"""

    def test_root_redirects(self, client):
        """Test root serves the redirect page"""
        response = client.get("/")
        assert response.status_code == 200
        assert "/dashboard" in response.text

    def test_dashboard_page(self, client):
        """Test dashboard page renders the dependency tree view"""
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert "Recur" in response.text
        # The page renders the topology as a semantic tree from the forest API
        assert "loadForest" in response.text
        assert "/api/v1/systems/forest" in response.text
        assert 'role="tree"' in response.text
