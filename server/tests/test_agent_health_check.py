"""
Unit tests for agent/health_check_utils.py (imported from the agent directory).

Network calls (urllib/socket) and external commands are monkeypatched —
no real network, no real subprocesses.
"""

import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "agent"))
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

import health_check_utils as hcu  # type: ignore[import-not-found]  # noqa: E402


def _proc(returncode=0, stdout=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


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
                {
                    "name": "http_ok",
                    "type": "http",
                    "url": "http://a/",
                    "expected_status": 200,
                    "timeout": 2,
                },
                {
                    "name": "https_bad",
                    "type": "https",
                    "url": "https://b/",
                    "expected_status": 200,
                    "timeout": 2,
                },
                {"name": "tcp_ok", "type": "tcp", "host": "127.0.0.1", "port": 5432, "timeout": 2},
                {"name": "ping_ok", "type": "ping", "host": "127.0.0.1", "timeout": 2},
                {"name": "cmd_ok", "type": "command", "command": "true", "timeout": 2},
                {
                    "name": "script_ok",
                    "type": "script",
                    "path": str(tmp_path / "ok.sh"),
                    "timeout": 2,
                },
                {
                    "name": "flaky",
                    "type": "command",
                    "command": "flaky",
                    "timeout": 2,
                    "max_retries": 2,
                },
                {"name": "unknown_type", "type": "warp", "timeout": 2},
            ],
            "dependencies": [
                {
                    "name": "Nested Dep",
                    "tasks": [
                        {"name": "dep_task", "type": "command", "command": "dep", "timeout": 2},
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
        monkeypatch.setattr(hcu, "_request_status", lambda url, timeout: 200)
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task(
            {"name": "h", "type": "http", "url": "http://x/", "expected_status": 200}
        )
        assert result["status"] == "UP"
        assert result["error"] is None
        assert result["task_id"] == "h"

    def test_http_unexpected_code_is_down(self, config_path, monkeypatch):
        monkeypatch.setattr(hcu, "_request_status", lambda url, timeout: 500)
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task(
            {"name": "h", "type": "http", "url": "http://x/", "expected_status": 200}
        )
        assert result["status"] == "DOWN"
        assert "500" in result["error"]

    def test_https_success(self, config_path, monkeypatch):
        monkeypatch.setattr(hcu, "_request_status", lambda url, timeout: 200)
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task(
            {"name": "h", "type": "https", "url": "https://x/", "expected_status": 200}
        )
        assert result["status"] == "UP"

    def test_http_httperror_code_is_down(self, config_path, monkeypatch):
        def boom(url, timeout):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

        monkeypatch.setattr(hcu, "_request_status", boom)
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task(
            {"name": "h", "type": "http", "url": "http://x/", "expected_status": 200}
        )
        assert result["status"] == "DOWN"
        assert "404" in result["error"]

    def test_http_httperror_expected_code_is_up(self, config_path, monkeypatch):
        def boom(url, timeout):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

        monkeypatch.setattr(hcu, "_request_status", boom)
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task(
            {"name": "h", "type": "http", "url": "http://x/", "expected_status": 404}
        )
        assert result["status"] == "UP"

    def test_http_connection_error_is_down(self, config_path, monkeypatch):
        def boom(url, timeout):
            raise OSError("Connection refused")

        monkeypatch.setattr(hcu, "_request_status", boom)
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task({"name": "h", "type": "http", "url": "http://x/"})
        assert result["status"] == "DOWN"
        assert "Request failed" in result["error"]

    def test_http_missing_url(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch)
        result = agent._execute_task({"name": "h", "type": "http"})
        assert result["status"] == "DOWN"
        assert "url" in result["error"]

    def test_tcp_success(self, config_path, monkeypatch):
        monkeypatch.setattr(hcu, "_tcp_connect", lambda host, port, timeout: None)
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task({"name": "t", "type": "tcp", "host": "127.0.0.1", "port": 1})
        assert result["status"] == "UP"

    def test_tcp_failure(self, config_path, monkeypatch):
        def boom(host, port, timeout):
            raise OSError("Connection refused")

        monkeypatch.setattr(hcu, "_tcp_connect", boom)
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task({"name": "t", "type": "tcp", "host": "127.0.0.1", "port": 1})
        assert result["status"] == "DOWN"

    def test_tcp_timeout(self, config_path, monkeypatch):
        import socket as _socket

        def boom(host, port, timeout):
            raise _socket.timeout("timed out")

        monkeypatch.setattr(hcu, "_tcp_connect", boom)
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task({"name": "t", "type": "tcp", "host": "127.0.0.1", "port": 1})
        assert result["status"] == "DOWN"
        assert "timeout" in result["error"].lower()

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
        result = agent._execute_task({"name": "c", "type": "command", "command": "true"})
        assert result["status"] == "UP"

    def test_command_failure(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(3))
        result = agent._execute_task({"name": "c", "type": "command", "command": "false"})
        assert result["status"] == "DOWN"
        assert "3" in result["error"]

    def test_script_success(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(0))
        result = agent._execute_task({"name": "s", "type": "script", "path": str(config_path)})
        assert result["status"] == "UP"

    def test_script_failure(self, config_path, monkeypatch):
        agent = _agent(config_path, monkeypatch, _proc(1))
        result = agent._execute_task({"name": "s", "type": "script", "path": str(config_path)})
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
        result = agent._execute_task({"name": "c", "type": "command", "command": "x"})
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

        result = agent._execute_task({"name": "c", "type": "command", "command": "x"})
        assert result["status"] == "DOWN"
        assert len(fake.calls) == 1


@pytest.mark.unit
class TestRecursiveEvaluation:
    """Nested dependency evaluation and report shape"""

    def test_nested_down_makes_root_down(self, config_path, monkeypatch):
        # http_ok=UP, https_bad=DOWN (500), tcp/ping/cmd/script=UP,
        # flaky=UP on first try, unknown=UNKNOWN, dep_task=UP
        http_codes = [200, 500]  # http_ok, https_bad
        calls = {"n": 0}

        def fake_request(url, timeout):
            code = http_codes[min(calls["n"], len(http_codes) - 1)]
            calls["n"] += 1
            return code

        monkeypatch.setattr(hcu, "_request_status", fake_request)
        monkeypatch.setattr(hcu, "_tcp_connect", lambda host, port, timeout: None)
        fake = _make_run(
            _proc(0),  # ping_ok
            _proc(0),  # cmd_ok
            _proc(0),  # script_ok
            _proc(0),  # flaky
            _proc(0),  # dep_task
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
        path.write_text(
            yaml.safe_dump(
                {
                    "system": {
                        "name": "All Up",
                        "tasks": [
                            {"name": "c", "type": "command", "command": "true"},
                        ],
                    }
                }
            )
        )
        fake = _make_run(_proc(0))
        monkeypatch.setattr(hcu.subprocess, "run", fake)
        agent = hcu.HealthCheckAgent(str(path), agent_id="unit-agent")

        results = agent.execute_checks()
        assert results["status"] == "UP"
        assert results["system_id"] == "all-up"

    def test_report_envelope_shape(self, config_path, monkeypatch):
        monkeypatch.setattr(hcu, "_request_status", lambda url, timeout: 200)
        monkeypatch.setattr(hcu, "_tcp_connect", lambda host, port, timeout: None)
        monkeypatch.setattr(hcu.subprocess, "run", _make_run(_proc(0)))
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


@pytest.mark.unit
class TestVendoredYaml:
    """The agent must run on a bare python3 without PyYAML installed."""

    def test_bootstrap_prefers_system_yaml(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            pytest.skip("No system PyYAML in this environment")
        import yaml as system_yaml

        assert hcu.yaml is system_yaml

    def test_vendored_fallback_without_system_yaml(self):
        # A meta path finder hides the system 'yaml' (ImportError) but
        # defers to normal resolution once the vendor dir is on sys.path —
        # exactly the window _bootstrap.ensure_yaml() creates.
        code = (
            "import sys, importlib.abc\n"
            "class Blocker(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] != 'yaml':\n"
            "            return None\n"
            "        for entry in sys.path:\n"
            "            if entry and entry.rstrip('/').endswith('vendor'):\n"
            "                return None\n"
            "        raise ImportError('system yaml hidden for test')\n"
            "sys.meta_path.insert(0, Blocker())\n"
            f"sys.path.insert(0, {AGENT_DIR!r})\n"
            "import health_check_utils as m\n"
            "print(m.yaml.__file__)\n"
            "print(m.yaml.safe_load('a: 1'))\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
        )
        assert out.returncode == 0, out.stderr
        lines = out.stdout.splitlines()
        assert "vendor" in lines[0]
        assert "{'a': 1}" in out.stdout

    def test_vendored_yaml_package_is_complete(self):
        vendor = Path(AGENT_DIR) / "vendor"
        expected = {
            "__init__.py",
            "composer.py",
            "constructor.py",
            "cyaml.py",
            "dumper.py",
            "emitter.py",
            "error.py",
            "events.py",
            "loader.py",
            "nodes.py",
            "parser.py",
            "reader.py",
            "representer.py",
            "resolver.py",
            "scanner.py",
            "serializer.py",
            "tokens.py",
        }
        missing = [f for f in expected if not (vendor / "yaml" / f).is_file()]
        assert not missing, f"missing vendored files: {missing}"
        assert (vendor / "LICENSE").is_file()


@pytest.mark.unit
class TestAgentCli:
    """recur_agent.py CLI wiring (report subcommand end-to-end)"""

    def test_report_subcommand_prints_envelope(self, tmp_path):
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(
            "system:\n"
            "  name: CLI Test\n"
            "  interval: 30\n"
            "  tasks:\n"
            "    - name: ok\n"
            "      type: command\n"
            "      command: 'true'\n"
        )
        env = dict(os.environ)
        env["RECUR_AGENT_CONFIG_FILE"] = str(cfg)
        env["RECUR_AGENT_LOG_FILE"] = str(tmp_path / "agent.log")
        env.pop("RECUR_AGENT_ENV_FILE", None)
        out = subprocess.run(
            [sys.executable, os.path.join(AGENT_DIR, "recur_agent.py"), "report"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            cwd=str(tmp_path),
        )
        assert out.returncode == 0, out.stderr
        report = json.loads(out.stdout)
        assert report["agent_id"]
        assert report["system_status"]["system_id"] == "cli-test"
        assert report["system_status"]["status"] == "UP"
