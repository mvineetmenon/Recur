#!/usr/bin/env python3
"""
Recur Agent Health Check Utilities
Python helper for agent to handle YAML parsing and health checks
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


class HealthCheckAgent:
    """Main health check agent class"""

    def __init__(self, config_file: str, agent_id: Optional[str] = None):
        """Initialize agent with configuration"""
        self.config_file = Path(config_file)
        self.agent_id = agent_id or subprocess.check_output(["hostname"], text=True).strip()
        self.config = self._load_config()
        self.timestamp = datetime.utcnow().isoformat() + "Z"

    def _load_config(self) -> Dict[str, Any]:
        """Load and parse YAML configuration"""
        if not self.config_file.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_file}")

        with open(self.config_file) as f:
            config = yaml.safe_load(f)

        if not config or "system" not in config:
            raise ValueError("Invalid config: missing 'system' key")

        return config

    def execute_checks(self) -> Dict[str, Any]:
        """Execute all configured health checks"""
        system = self.config["system"]
        system_id = system.get("id") or system.get("name", "unknown").lower().replace(" ", "-")

        results = {
            "system_id": system_id,
            "name": system.get("name"),
            "timestamp": self.timestamp,
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

    def _execute_system(self, system: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively execute checks for a system"""
        system_id = system.get("id") or system.get("name", "unknown").lower().replace(" ", "-")

        results = {
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
        """Execute a single health check task"""
        name = task.get("name", "unknown")
        task_type = task.get("type", "http").lower()
        timeout = task.get("timeout", 5)

        start_time = time.time()

        try:
            if task_type in ("http", "https"):
                status, error = self._check_http(task, timeout)
            elif task_type == "tcp":
                status, error = self._check_tcp(task, timeout)
            elif task_type == "ping":
                status, error = self._check_ping(task, timeout)
            elif task_type == "command":
                status, error = self._check_command(task, timeout)
            else:
                status, error = "UNKNOWN", f"Unknown task type: {task_type}"

        except Exception as e:
            status, error = "DOWN", str(e)

        duration_ms = (time.time() - start_time) * 1000

        return {
            "task_id": name,
            "name": name,
            "type": task_type,
            "status": status,
            "duration_ms": duration_ms,
            "error": error if error else None,
        }

    def _check_http(self, task: Dict[str, Any], timeout: float) -> tuple[str, str]:
        """HTTP/HTTPS health check"""
        url = task.get("url")
        expected_status = task.get("expected_status", 200)

        if not url:
            return "DOWN", "Missing 'url' parameter"

        try:
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "--max-time",
                    str(timeout),
                    "--connect-timeout",
                    "3",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 1,
            )

            http_code = int(result.stdout.strip())

            if http_code == expected_status:
                return "UP", ""
            else:
                return "DOWN", f"HTTP {http_code} (expected {expected_status})"

        except (subprocess.TimeoutExpired, ValueError) as e:
            return "DOWN", f"Request failed: {e}"

    def _check_tcp(self, task: Dict[str, Any], timeout: float) -> tuple[str, str]:
        """TCP port check"""
        host = task.get("host")
        port = task.get("port")

        if not host or not port:
            return "DOWN", "Missing 'host' or 'port' parameter"

        try:
            result = subprocess.run(
                ["bash", "-c", f"timeout {timeout} bash -c 'echo >/dev/tcp/{host}/{port}'"],
                capture_output=True,
                text=True,
                timeout=timeout + 1,
            )

            if result.returncode == 0:
                return "UP", ""
            else:
                return "DOWN", f"Connection failed to {host}:{port}"

        except subprocess.TimeoutExpired:
            return "DOWN", f"Connection timeout to {host}:{port}"

    def _check_ping(self, task: Dict[str, Any], timeout: float) -> tuple[str, str]:
        """ICMP ping check"""
        host = task.get("host")

        if not host:
            return "DOWN", "Missing 'host' parameter"

        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout)), host],
                capture_output=True,
                text=True,
                timeout=timeout + 1,
            )

            if result.returncode == 0:
                return "UP", ""
            else:
                return "DOWN", "Ping failed"

        except subprocess.TimeoutExpired:
            return "DOWN", "Ping timeout"

    def _check_command(self, task: Dict[str, Any], timeout: float) -> tuple[str, str]:
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

    def to_json(self) -> str:
        """Generate JSON report"""
        results = self.execute_checks()
        return json.dumps(results, indent=2)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Recur Health Check Agent")
    parser.add_argument(
        "--config",
        default="/etc/recur/config.yaml",
        help="Configuration file path",
    )
    parser.add_argument(
        "--agent-id",
        help="Agent ID (defaults to hostname)",
    )
    parser.add_argument(
        "--output",
        help="Output file (defaults to stdout)",
    )

    args = parser.parse_args()

    try:
        agent = HealthCheckAgent(args.config, args.agent_id)
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
