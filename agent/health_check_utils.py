#!/usr/bin/env python3
"""
Recur Agent Health Check Utilities
Python check executor for the Recur agent.

Uses only the Python standard library (urllib, socket, subprocess) plus
PyYAML for config parsing. PyYAML is resolved via _bootstrap, which falls
back to the pure-Python copy vendored in agent/vendor/ when the system
Python does not provide it (air-gapped hosts: python3 is the only
requirement).
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from _bootstrap import ensure_yaml

yaml = ensure_yaml()


def _request_status(url: str, timeout: float) -> int:
    """GET ``url`` and return the HTTP status code.

    Raises ``OSError`` (including ``URLError`` and socket timeouts) on
    connection failure.
    """
    context = ssl.create_default_context() if url.lower().startswith("https://") else None
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.status


def _tcp_connect(host: str, port: int, timeout: float) -> None:
    """Open a TCP connection to ``host:port``; raises ``OSError`` on failure."""
    with socket.create_connection((host, port), timeout=timeout):
        return


class HealthCheckAgent:
    """Main health check agent class"""

    def __init__(self, config_file: str, agent_id: Optional[str] = None):
        """Initialize agent with configuration"""
        self.config_file = Path(config_file)
        self.agent_id = agent_id or socket.gethostname()
        self.config = self._load_config()
        self.timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _load_config(self) -> Dict[str, Any]:
        """Load and parse YAML configuration"""
        if not self.config_file.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_file}")

        with open(self.config_file) as f:
            config = yaml.safe_load(f)

        if not config or "system" not in config:
            raise ValueError("Invalid config: missing 'system' key")

        return config

    @property
    def system(self) -> Dict[str, Any]:
        """Root system definition"""
        return self.config["system"]

    def get_interval(self) -> int:
        """Root system check interval in seconds (default 60)"""
        try:
            return int(self.system.get("interval", 60))
        except (TypeError, ValueError):
            return 60

    def execute_checks(self) -> Dict[str, Any]:
        """Execute all configured health checks"""
        system = self.system
        system_id = system.get("id") or system.get("name", "unknown").lower().replace(" ", "-")

        results = {
            "system_id": system_id,
            "name": system.get("name"),
            "timestamp": self.timestamp,
            "status": "UP",
            "tasks": [],
            "dependencies": [],
        }

        # _execute_system already guarantees status is "UP" or "DOWN"
        # (any non-UP task or dependency rolls the system down)
        results.update(self._execute_system(system, system_id))

        return results

    def _execute_system(
        self, system: Dict[str, Any], system_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Recursively execute checks for a system"""
        if system_id is None:
            system_id = system.get("id") or system.get("name", "unknown").lower().replace(" ", "-")

        results: Dict[str, Any] = {
            "system_id": system_id,
            "name": system.get("name"),
            "status": "UP",
            "tasks": [],
            "dependencies": [],
        }

        # Execute tasks
        for task in system.get("tasks", []):
            result = self._execute_task(task)
            results["tasks"].append(result)
            if result["status"] != "UP":
                results["status"] = "DOWN"

        # Execute dependencies recursively
        for dep in system.get("dependencies", []):
            dep_result = self._execute_system(dep)
            results["dependencies"].append(dep_result)
            if dep_result["status"] != "UP":
                results["status"] = "DOWN"

        return results

    def _execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single health check task (with retries)"""
        name = task.get("name", "unknown")
        task_type = str(task.get("type", "http")).lower()
        timeout = task.get("timeout", 5)
        max_retries = int(task.get("max_retries", 0) or 0)

        start_time = time.time()
        status, error = "UNKNOWN", "Unknown task type"

        for attempt in range(max_retries + 1):
            try:
                if task_type in ("http", "https"):
                    status, error = self._check_http(task, timeout)
                elif task_type == "tcp":
                    status, error = self._check_tcp(task, timeout)
                elif task_type == "ping":
                    status, error = self._check_ping(task, timeout)
                elif task_type == "command":
                    status, error = self._check_command(task, timeout)
                elif task_type == "script":
                    status, error = self._check_script(task, timeout)
                else:
                    status, error = "UNKNOWN", f"Unknown task type: {task_type}"
            except Exception as e:
                status, error = "DOWN", str(e)

            if status == "UP":
                break
            if attempt < max_retries:
                time.sleep(0.1)

        duration_ms = (time.time() - start_time) * 1000

        return {
            "task_id": name,
            "name": name,
            "type": task_type,
            "status": status,
            "duration_ms": duration_ms,
            "error": error if error else None,
        }

    def _check_http(self, task: Dict[str, Any], timeout: float) -> Tuple[str, str]:
        """HTTP/HTTPS health check (stdlib urllib; no curl required)"""
        url = task.get("url")
        expected_status = task.get("expected_status", 200)

        if not url:
            return "DOWN", "Missing 'url' parameter"

        try:
            http_code = _request_status(url, timeout)

            if http_code == expected_status:
                return "UP", ""
            else:
                return "DOWN", f"HTTP {http_code} (expected {expected_status})"

        except urllib.error.HTTPError as e:
            # HTTP errors carry a status code: compare against expectation
            if e.code == expected_status:
                return "UP", ""
            return "DOWN", f"HTTP {e.code} (expected {expected_status})"
        except (urllib.error.URLError, OSError, ValueError) as e:
            reason = getattr(e, "reason", None) or e
            return "DOWN", f"Request failed: {reason}"

    def _check_tcp(self, task: Dict[str, Any], timeout: float) -> Tuple[str, str]:
        """TCP port check (stdlib socket; no bash /dev/tcp required)"""
        host = task.get("host")
        port = task.get("port")

        if not host or not port:
            return "DOWN", "Missing 'host' or 'port' parameter"

        try:
            _tcp_connect(host, int(port), timeout)
            return "UP", ""
        except (OSError, ValueError) as e:
            detail = getattr(e, "reason", None) or e
            if isinstance(e, socket.timeout) or "timed out" in str(detail).lower():
                return "DOWN", f"Connection timeout to {host}:{port}"
            return "DOWN", f"Connection failed to {host}:{port}: {detail}"

    def _check_ping(self, task: Dict[str, Any], timeout: float) -> Tuple[str, str]:
        """ICMP ping check (requires the optional `ping` binary)"""
        host = task.get("host")

        if not host:
            return "DOWN", "Missing 'host' parameter"

        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout)) if timeout else "1", host],
                capture_output=True,
                text=True,
                timeout=timeout + 1,
            )

            if result.returncode == 0:
                return "UP", ""
            elif "not found" in (result.stderr or "") or "No such file" in (result.stderr or ""):
                return "DOWN", "ping binary not available on this host"
            else:
                return "DOWN", "Ping failed"

        except subprocess.TimeoutExpired:
            return "DOWN", "Ping timeout"
        except FileNotFoundError:
            return "DOWN", "ping binary not available on this host"

    def _check_command(self, task: Dict[str, Any], timeout: float) -> Tuple[str, str]:
        """Execute arbitrary shell command"""
        command = task.get("command")

        if not command:
            return "DOWN", "Missing 'command' parameter"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode == 0:
                return "UP", ""
            else:
                return "DOWN", f"Command failed with exit code {result.returncode}"

        except subprocess.TimeoutExpired:
            return "DOWN", "Command timeout"

    def _check_script(self, task: Dict[str, Any], timeout: float) -> Tuple[str, str]:
        """Execute a standalone script (exit code 0 = UP)"""
        path = task.get("path")

        if not path:
            return "DOWN", "Missing 'path' parameter"

        script = Path(path)
        if not script.exists():
            return "DOWN", f"Script not found: {path}"

        try:
            result = subprocess.run(
                [str(script)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode == 0:
                return "UP", ""
            else:
                return "DOWN", f"Script failed with exit code {result.returncode}"

        except subprocess.TimeoutExpired:
            return "DOWN", "Script timeout"
        except OSError as e:
            return "DOWN", f"Could not execute script: {e}"

    def build_report(self) -> Dict[str, Any]:
        """Full report envelope as the server expects it"""
        system_status = self.execute_checks()
        return {
            "agent_id": self.agent_id,
            "timestamp": system_status["timestamp"],
            "system_status": system_status,
        }

    def to_json(self) -> str:
        """Generate JSON report (full envelope)"""
        return json.dumps(self.build_report(), indent=2)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Recur Health Check Agent")
    parser.add_argument(
        "--config",
        default=os.environ.get("RECUR_AGENT_CONFIG_FILE", "/etc/recur/config.yaml"),
        help="Configuration file path (or RECUR_AGENT_CONFIG_FILE)",
    )
    parser.add_argument(
        "--agent-id",
        help="Agent ID (defaults to hostname)",
    )
    parser.add_argument(
        "--output",
        help="Output file (defaults to stdout)",
    )
    parser.add_argument(
        "--print-interval",
        action="store_true",
        help="Print the root system check interval (seconds) and exit",
    )

    args = parser.parse_args()

    try:
        agent = HealthCheckAgent(args.config, args.agent_id)

        if args.print_interval:
            print(agent.get_interval())
            return

        report = agent.to_json()

        if args.output:
            with open(args.output, "w") as f:
                f.write(report)
        else:
            print(report)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
