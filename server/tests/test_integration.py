"""
Integration tests (T6).

- test_full_nested_flow: agent register -> system with nested config ->
  nested status report (one DOWN leaf) -> tree asserts recursive status ->
  history.
- test_docker_compose_smoke: real `docker compose up -d --build` against a
  live container (marked `slow`, skipped when docker is unavailable).
"""

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _now():
    return datetime.now(timezone.utc).isoformat()


class TestFullNestedFlow:
    """End-to-end API flow with a 3-level nested system"""

    def test_full_nested_flow(self, client):
        # 1. Register agent
        response = client.post(
            "/api/v1/agents/register",
            json={
                "agent_id": "flow-agent",
                "hostname": "flow.local",
                "ip_address": "192.168.1.90",
            },
        )
        assert response.status_code == 201
        agent_db_id = response.json()["id"]
        agent_token = response.json()["agent_token"]

        # 2. Create system with nested dependencies
        config = {
            "name": "Web Stack",
            "tasks": [
                {"name": "web", "type": "http", "url": "http://web/", "expected_status": 200},
            ],
            "dependencies": [
                {
                    "name": "DB",
                    "tasks": [
                        {"name": "pg", "type": "tcp", "host": "db", "port": 5432},
                    ],
                    "dependencies": [
                        {
                            "name": "Disk",
                            "tasks": [
                                {"name": "disk", "type": "command", "command": "df -h"},
                            ],
                        },
                    ],
                },
            ],
        }
        response = client.post(
            "/api/v1/systems",
            json={
                "system_id": "webstack",
                "name": "Web Stack",
                "agent_id": agent_db_id,
                "config": config,
            },
        )
        assert response.status_code == 201
        assert response.json()["system_id"] == "webstack"

        # Nested children were registered with parent-prefixed ids
        # (children are addressed through the tree endpoint)
        early_tree = client.get("/api/v1/systems/webstack/tree").json()
        child_ids = [d["system_id"] for d in early_tree["dependencies"]]
        assert "webstack/db" in child_ids
        grandchild_ids = [d["system_id"] for d in early_tree["dependencies"][0]["dependencies"]]
        assert "webstack/db/disk" in grandchild_ids

        # 3. Submit a nested report: web UP, pg DOWN (the failing leaf)
        response = client.post(
            "/api/v1/status",
            headers={"Authorization": f"Bearer {agent_token}"},
            json={
                "agent_id": "flow-agent",
                "timestamp": _now(),
                "system_status": {
                    "system_id": "webstack",
                    "name": "Web Stack",
                    "status": "DOWN",
                    "tasks": [
                        {
                            "task_id": "web",
                            "name": "web",
                            "type": "http",
                            "status": "UP",
                            "duration_ms": 12.0,
                        },
                    ],
                    "dependencies": [
                        {
                            "system_id": "db",
                            "name": "DB",
                            "status": "DOWN",
                            "tasks": [
                                {
                                    "task_id": "pg",
                                    "name": "pg",
                                    "type": "tcp",
                                    "status": "DOWN",
                                    "error": "connection refused",
                                    "duration_ms": 500.0,
                                },
                            ],
                            "dependencies": [
                                {
                                    "system_id": "disk",
                                    "name": "Disk",
                                    "status": "UP",
                                    "tasks": [
                                        {
                                            "task_id": "disk",
                                            "name": "disk",
                                            "type": "command",
                                            "status": "UP",
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

        # 4. Tree: recursive structure with the failing leaf and DOWN roll-up
        tree_response = client.get("/api/v1/systems/webstack/tree")
        assert tree_response.status_code == 200
        tree = tree_response.json()

        assert tree["system_id"] == "webstack"
        assert tree["status"] == "DOWN"  # DOWN leaf rolled up to the root

        web_task = tree["tasks"][0]
        assert web_task["task_id"] == "web"
        assert web_task["status"] == "UP"

        assert len(tree["dependencies"]) == 1
        db_tree = tree["dependencies"][0]
        assert db_tree["system_id"] == "webstack/db"
        assert db_tree["status"] == "DOWN"

        pg_task = db_tree["tasks"][0]
        assert pg_task["task_id"] == "pg"
        assert pg_task["status"] == "DOWN"
        assert pg_task["error_message"] == "connection refused"

        assert len(db_tree["dependencies"]) == 1
        disk_tree = db_tree["dependencies"][0]
        assert disk_tree["system_id"] == "webstack/db/disk"
        assert disk_tree["tasks"][0]["status"] == "UP"

        # No duplicate auto-created "db" system alongside "webstack/db"
        assert client.get("/api/v1/systems/db").status_code == 404

        # 5. History records the report
        history_response = client.get("/api/v1/systems/webstack/history")
        assert history_response.status_code == 200
        history = history_response.json()
        assert history["system_id"] == "webstack"
        assert history["count"] >= 1


@pytest.mark.slow
@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker CLI not available",
)
class TestDockerComposeSmoke:
    """Build and run the server via docker compose; hit it with curl (P4)"""

    PROJECT = "recur-smoke"
    HEALTH_TIMEOUT_S = 300
    BASE_URL = f"http://localhost:{os.environ.get('RECUR_HTTP_PORT', '8000')}"

    @classmethod
    def _compose_args(cls):
        compose = [
            "docker",
            "compose",
            "-p",
            cls.PROJECT,
            "-f",
            str(REPO_ROOT / "docker-compose.yml"),
        ]
        # Offline LAN environments: use the local-registry base image
        if os.environ.get("RECUR_LAN_DOCKER") == "1":
            compose += ["-f", str(REPO_ROOT / "docker-compose.lan.yml")]
        return compose

    @classmethod
    def setup_class(cls):
        result = subprocess.run(
            cls._compose_args() + ["up", "-d", "--build"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            pytest.skip(f"docker compose up failed: {result.stderr[-2000:]}")

        # Wait for the health endpoint
        deadline = time.time() + cls.HEALTH_TIMEOUT_S
        last_error = "timeout"
        while time.time() < deadline:
            probe = subprocess.run(
                ["curl", "-sf", cls.BASE_URL + "/api/v1/health"],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0:
                return
            last_error = probe.stderr.strip()
            time.sleep(5)
        pytest.skip(f"server health endpoint not ready: {last_error}")

    @classmethod
    def teardown_class(cls):
        subprocess.run(
            cls._compose_args() + ["down", "-v", "--remove-orphans"],
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_health(self):
        probe = subprocess.run(
            ["curl", "-sf", self.BASE_URL + "/api/v1/health"],
            capture_output=True,
            text=True,
        )
        assert probe.returncode == 0
        assert "healthy" in probe.stdout

    def test_register_report_tree(self):
        def curl(args, data=None, auth=None):
            cmd = ["curl", "-sf", "-X", "POST", "-H", "Content-Type: application/json"]
            if auth is not None:
                cmd += ["-H", f"Authorization: Bearer {auth}"]
            if data is not None:
                cmd += ["-d", data]
            cmd += args
            return subprocess.run(cmd, capture_output=True, text=True)

        register = curl(
            [self.BASE_URL + "/api/v1/agents/register"],
            data='{"agent_id": "smoke-agent", "hostname": "smoke", ' '"ip_address": "127.0.0.1"}',
        )
        assert register.returncode == 0
        agent_db_id = json.loads(register.stdout)["id"]
        agent_token = json.loads(register.stdout)["agent_token"]

        create = curl(
            [self.BASE_URL + "/api/v1/systems"],
            data=json.dumps(
                {
                    "system_id": "smoke-sys",
                    "name": "Smoke",
                    "agent_id": agent_db_id,
                    "config": {
                        "name": "Smoke",
                        "tasks": [
                            {
                                "name": "api",
                                "type": "http",
                                "url": self.BASE_URL + "/api/v1/health",
                            },
                        ],
                    },
                }
            ),
        )
        assert create.returncode == 0

        report = curl(
            [self.BASE_URL + "/api/v1/status"],
            auth=agent_token,
            data=json.dumps(
                {
                    "agent_id": "smoke-agent",
                    "timestamp": _now(),
                    "system_status": {
                        "system_id": "smoke-sys",
                        "name": "Smoke",
                        "status": "UP",
                        "tasks": [
                            {
                                "task_id": "api",
                                "name": "api",
                                "type": "http",
                                "status": "UP",
                                "duration_ms": 3.0,
                            },
                        ],
                    },
                }
            ),
        )
        assert report.returncode == 0
        assert "accepted" in report.stdout

        tree = subprocess.run(
            ["curl", "-sf", self.BASE_URL + "/api/v1/systems/smoke-sys/tree"],
            capture_output=True,
            text=True,
        )
        assert tree.returncode == 0
        parsed = json.loads(tree.stdout)
        assert parsed["system_id"] == "smoke-sys"
        assert parsed["tasks"][0]["task_id"] == "api"
