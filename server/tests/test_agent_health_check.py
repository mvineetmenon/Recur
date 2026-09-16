"""
Unit tests for agent/health_check_utils.py (imported from the agent directory).

All external commands are monkeypatched — no network, no real subprocesses.
"""

import json
import os
import subprocess
import sys

import pytest

AGENT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "agent")
)
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import health_check_utils as hcu  # noqa: E402


def _proc(returncode=0, stdout=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


def _make_run(*results):
    """Fake subprocess.run returning queued results (last repeats)"""
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        idx = min(len(calls) - 1, len(results) - 1)
        return results[idx]

    fake_run.calls = calls
    return fake_run


@pytest.fixture
def config_path(tmp_path):
    """A config exercising every task type plus one nested dependency"""
    cfg = {
        "system": {
            "name": "Test System",
            "interval": 45,
            "tasks": [
                {"name": "http_ok", "type": "http", "url": "http://a/",
                 "expected_status": 200, "timeout": 2},
                {"name": "https_bad", "type": "https", "url": "https://b/",
                 "expected_status": 200, "timeout": 2},
                {"name": "tcp_ok", "type": "tcp", "host": "127.0.0.1",
                 "port": 5432, "timeout": 2},
                {"name": "ping_ok", "type": "ping", "host": "127.0.0.1",
                 "timeout": 2},
                {"name": "cmd_ok", "type": "command", "command": "true",
                 "timeout": 2},
                {"name": "script_ok", "type": "script", "path": str(
                    tmp_path / "ok.sh"), "timeout": 2},
                {"name": "flaky", "type": "command", "command": "flaky",
                 "timeout": 2, "max_retries": 2},
                {"name": "unknown_type", "type": "warp", "timeout": 2},
            ],
            "dependencies": [
                {
                    "name": "Nested Dep",
                    "tasks": [
                        {"name": "dep_task", "type": "command",
                         "command": "dep", "timeout": 2},
                    ],
                },
            ],
        }
    }
    import yaml

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    script = tmp_path / "ok.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    return path


def _agent(config_path, monkeypatch, *results, agent_id="unit-agent"):
    """Build an agent with subprocess.run faked to return queued results"""
    monkeypatch.setattr(hcu.subprocess, "run", _make_run(*results))
    return hcu.HealthCheckAgent(str(config_path), agent_id=agent_id)


@pytest.mark.unit
class TestTaskTypes:
    """Every task type: success and failure paths"""

    def test_http_success(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(0, "200"))
        result = agent._execute_task(
            {"name": "h", "type": "http", "url": "http://x/", "expected_status": 200}
        )
        assert result["status"] == "UP"
        assert result["error"] is None
        assert result["task_id"] == "h"

    def test_http_unexpected_code_is_down(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(0, "500"))
        result = agent._execute_task(
            {"name": "h", "type": "http", "url": "http://x/", "expected_status": 200}
        )
        assert result["status"] == "DOWN"
        assert "500" in result["error"]

    def test_https_success(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(0, "200"))
        result = agent._execute_task(
            {"name": "h", "type": "https", "url": "https://x/", "expected_status": 200}
        )
        assert result["status"] == "UP"

    def test_http_missing_url(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch)
        result = agent._execute_task({"name": "h", "type": "http"})
        assert result["status"] == "DOWN"
        assert "url" in result["error"]

    def test_tcp_success(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task(
            {"name": "t", "type": "tcp", "host": "127.0.0.1", "port": 1}
        )
        assert result["status"] == "UP"

    def test_tcp_failure(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(1))
        result = agent._execute_task(
            {"name": "t", "type": "tcp", "host": "127.0.0.1", "port": 1}
        )
        assert result["status"] == "DOWN"

    def test_tcp_missing_params(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch)
        result = agent._execute_task({"name": "t", "type": "tcp"})
        assert result["status"] == "DOWN"

    def test_ping_success(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task({"name": "p", "type": "ping", "host": "x"})
        assert result["status"] == "UP"

    def test_ping_failure(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(1))
        result = agent._execute_task({"name": "p", "type": "ping", "host": "x"})
        assert result["status"] == "DOWN"

    def test_command_success(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task(
            {"name": "c", "type": "command", "command": "true"}
        )
        assert result["status"] == "UP"

    def test_command_failure(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(3))
        result = agent._execute_task(
            {"name": "c", "type": "command", "command": "false"}
        )
        assert result["status"] == "DOWN"
        assert "3" in result["error"]

    def test_script_success(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task(
            {"name": "s", "type": "script", "path": str(config_path)}
        )
        assert result["status"] == "UP"

    def test_script_failure(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(1))
        result = agent._execute_task(
            {"name": "s", "type": "script", "path": str(config_path)}
        )
        assert result["status"] == "DOWN"
        assert "1" in result["error"]

    def test_script_missing(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch)
        result = agent._execute_task(
            {"name": "s", "type": "script", "path": "/nonexistent/script.sh"}
        )
        assert result["status"] == "DOWN"
        assert "not found" in result["error"]

    def test_unknown_task_type(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch)
        result = agent._execute_task({"name": "u", "type": "warp"})
        assert result["status"] == "UNKNOWN"

    def test_unexpected_exception_is_down(self, config_path, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("kaput")

        monkeypatch.setattr(hcu.subprocess, "run", boom)
        agent = hcu.HealthCheckAgent(str(config_path), agent_id="unit-agent")
        result = agent._execute_task(
            {"name": "c", "type": "command", "command": "x"}
        )
        assert result["status"] == "DOWN"
        assert "kaput" in result["error"]


@pytest.mark.unit
class TestRetries:
    """max_retries is honored from task config"""

    def test_retry_succeeds_on_third_attempt(self, config_path, monkeypatch):
        fake = _make_run(_proc(1), _proc(1), _proc(0))
        monkeypatch.setattr(hcu.subprocess, "run", fake)
        agent = hcu.HealthCheckAgent(str(config_path), agent_id="unit-agent")

        result = agent._execute_task(
            {"name": "c", "type": "command", "command": "x", "max_retries": 2}
        )
        assert result["status"] == "UP"
        assert len(fake.calls) == 3

    def test_retry_exhausted_stays_down(self, config_path, monkeypatch):
        fake = _make_run(_proc(1))
        monkeypatch.setattr(hcu.subprocess, "run", fake)
        agent = hcu.HealthCheckAgent(str(config_path), agent_id="unit-agent")

        result = agent._execute_task(
            {"name": "c", "type": "command", "command": "x", "max_retries": 2}
        )
        assert result["status"] == "DOWN"
        assert len(fake.calls) == 3

    def test_no_retry_single_call(self, config_path, monkeypatch):
        fake = _make_run(_proc(1))
        monkeypatch.setattr(hcu.subprocess, "run", fake)
        agent = hcu.HealthCheckAgent(str(config_path), agent_id="unit-agent")

        result = agent._execute_task(
            {"name": "c", "type": "command", "command": "x"}
        )
        assert result["status"] == "DOWN"
        assert len(fake.calls) == 1


@pytest.mark.unit
class TestRecursiveEvaluation:
    """Nested dependency evaluation and report shape"""

    def test_nested_down_makes_root_down(self, config_path, monkeypatch):
        # http_ok=UP, https_bad=DOWN (500), tcp/ping/cmd/script=UP,
        # flaky=UP on first try, unknown=UNKNOWN, dep_task=UP
        fake = _make_run(
            _proc(0, "200"),   # http_ok
            _proc(0, "500"),   # https_bad
            _proc(0),          # tcp_ok
            _proc(0),          # ping_ok
            _proc(0),          # cmd_ok
            _proc(0),          # script_ok
            _proc(0),          # flaky
            _proc(0),          # unknown_type (never runs, but queued)
            _proc(0),          # dep_task
        )
        monkeypatch.setattr(hcu.subprocess, "run", fake)
        agent = hcu.HealthCheckAgent(str(config_path), agent_id="unit-agent")

        results = agent.execute_checks()

        assert results["system_id"] == "test-system"
        assert results["status"] == "DOWN"

        statuses = {t["task_id"]: t["status"] for t in results["tasks"]}
        assert statuses["http_ok"] == "UP"
        assert statuses["https_bad"] == "DOWN"
        assert statuses["unknown_type"] == "UNKNOWN"

        assert len(results["dependencies"]) == 1
        dep = results["dependencies"][0]
        assert dep["system_id"] == "nested-dep"
        assert dep["status"] == "UP"
        assert dep["tasks"][0]["status"] == "UP"

    def test_all_up_root(self, tmp_path, monkeypatch):
        import yaml

        path = tmp_path / "up.yaml"
        path.write_text(yaml.safe_dump(
            {"system": {
                "name": "All Up",
                "tasks": [
                    {"name": "c", "type": "command", "command": "true"},
                ],
            }}
        ))
        fake = _make_run(_proc(0))
        monkeypatch.setattr(hcu.subprocess, "run", fake)
        agent = hcu.HealthCheckAgent(str(path), agent_id="unit-agent")

        results = agent.execute_checks()
        assert results["status"] == "UP"
        assert results["system_id"] == "all-up"

    def test_report_envelope_shape(self, config_path, monkeypatch):
        monkeypatch.setattr(hcu.subprocess, "run", _make_run(_proc(0, "200")))
        agent = hcu.HealthCheckAgent(str(config_path), agent_id="unit-agent")

        report = agent.build_report()
        assert report["agent_id"] == "unit-agent"
        assert "timestamp" in report
        ss = report["system_status"]
        assert ss["system_id"] == "test-system"
        assert "tasks" in ss and "dependencies" in ss

        # to_json must round-trip
        parsed = json.loads(agent.to_json())
        assert parsed["agent_id"] == "unit-agent"
        assert parsed["system_status"]["system_id"] == "test-system"


@pytest.mark.unit
class TestIntervalAndConfig:
    """get_interval and config loading"""

    def test_interval_from_config(self, config_path, monkeypatch):
        monkeypatch.setattr(hcu.subprocess, "run", _make_run(_proc(0)))
        agent = hcu.HealthCheckAgent(str(config_path), agent_id="unit-agent")
        assert agent.get_interval() == 45

    def test_interval_default(self, tmp_path):
        import yaml

        path = tmp_path / "no-interval.yaml"
        path.write_text(yaml.safe_dump({"system": {"name": "X", "tasks": []}}))
        agent = hcu.HealthCheckAgent(str(path), agent_id="unit-agent")
        assert agent.get_interval() == 60

    def test_missing_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            hcu.HealthCheckAgent(str(tmp_path / "nope.yaml"), agent_id="unit-agent")

    def test_invalid_config_raises(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("{}\n")
        with pytest.raises(ValueError):
            hcu.HealthCheckAgent(str(path), agent_id="unit-agent")
