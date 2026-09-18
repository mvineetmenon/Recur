#!/usr/bin/env python3
"""
Recur Health Check Agent

Single Python entry point (replaces the former bash recur-agent.sh).
Handles config/env, registration, the check loop, report submission and
heartbeat. All checks are executed by health_check_utils.py next to this
script.

Runtime requirement: python3 only. PyYAML is resolved via _bootstrap and
falls back to the pure-Python copy vendored in agent/vendor/, so hosts
without pip or OS package access work as long as python3 is present.

Usage:
    recur-agent {run|check|register|report}

Environment overrides (also from a .env file, see RECUR_AGENT_ENV_FILE):
    RECUR_AGENT_CONFIG_FILE  (default /etc/recur/config.yaml)
    RECUR_AGENT_SERVER_URL   (default http://localhost:8000)
    RECUR_AGENT_ID           (default: hostname)
    RECUR_AGENT_LOG_FILE     (default /var/log/recur-agent.log)
"""

from __future__ import annotations

import json
import logging
import os
import platform
import signal
import socket
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Ensure the script's real directory is importable (works through the
# /usr/local/bin/recur-agent symlink installed by install.sh).
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import health_check_utils  # noqa: E402

AGENT_VERSION = "0.2.0"
SERVER_TIMEOUT = 10.0

log = logging.getLogger("recur-agent")


################################################################################
# Environment and configuration
################################################################################


def load_env_file(env_file: str) -> None:
    """Load KEY=value overrides from a .env-style file.

    Mirrors the former bash behaviour (`set -a; source file`): values from
    the file override existing environment variables. Missing files are
    ignored.
    """
    path = Path(env_file)
    if not path.is_file():
        return

    log.info("Loading environment overrides from: %s", path)
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            os.environ[key] = value


def setup_logging(log_file: str) -> None:
    """Log to stderr and, best-effort, to ``log_file``.

    A non-writable log file (e.g. running unprivileged) must not stop the
    agent.
    """
    handlers = [logging.StreamHandler(sys.stderr)]
    try:
        handlers.append(logging.FileHandler(log_file))
    except OSError:
        log.warning("Cannot open log file %s; logging to stderr only", log_file)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def first_ipv4() -> str:
    """Best-effort first non-loopback IPv4 address (fallback 127.0.0.1)."""
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


################################################################################
# Server communication (stdlib urllib; no curl required)
################################################################################


def http_request(
    method: str, url: str, payload: Optional[Dict[str, Any]] = None, timeout: float = SERVER_TIMEOUT
) -> Tuple[int, str]:
    """Perform an HTTP request; returns (status_code, body_text)."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", None) or e
        raise ConnectionError(f"{url}: {reason}") from e


################################################################################
# Agent
################################################################################


class RecurAgent:
    def __init__(self) -> None:
        self.config_file = os.environ.get("RECUR_AGENT_CONFIG_FILE", "/etc/recur/config.yaml")
        self.server_url = os.environ.get("RECUR_AGENT_SERVER_URL", "http://localhost:8000").rstrip(
            "/"
        )
        self.agent_id = os.environ.get("RECUR_AGENT_ID") or socket.gethostname()
        self.registered = False
        self._stop = threading.Event()

    # -- config ---------------------------------------------------------------

    def load_config(self) -> None:
        """Exit if the config file does not exist (matches the old agent)."""
        if not Path(self.config_file).is_file():
            log.error("Configuration file not found: %s", self.config_file)
            sys.exit(1)
        log.info("Loading configuration from: %s", self.config_file)

    def _checker(self) -> health_check_utils.HealthCheckAgent:
        # Rebuilt each cycle so config edits are picked up live.
        return health_check_utils.HealthCheckAgent(self.config_file, self.agent_id)

    # -- server calls ---------------------------------------------------------

    def register(self) -> bool:
        log.info("Registering agent with server...")
        payload = {
            "agent_id": self.agent_id,
            "hostname": socket.gethostname(),
            "ip_address": first_ipv4(),
            "version": AGENT_VERSION,
            "os_type": platform.system(),
            "cpu_count": os.cpu_count(),
            "python_version": platform.python_version(),
        }
        try:
            status, body = http_request(
                "POST", f"{self.server_url}/api/v1/agents/register", payload
            )
        except ConnectionError as e:
            log.error("Failed to register agent: %s", e)
            return False

        if 200 <= status < 300 and "agent_id" in body:
            log.info("Agent registered successfully")
            self.registered = True
            return True

        log.error("Failed to register agent (HTTP %s): %s", status, body.strip())
        return False

    def build_report(self) -> Dict[str, Any]:
        return self._checker().build_report()

    def submit_report(self, report: Dict[str, Any]) -> bool:
        log.info("Submitting report to: %s/api/v1/status", self.server_url)
        try:
            status, body = http_request("POST", f"{self.server_url}/api/v1/status", report)
        except ConnectionError as e:
            log.error("Failed to submit report: %s", e)
            return False

        if 200 <= status < 300 and "status" in body:
            log.info("Report submitted successfully")
            return True

        log.error("Failed to submit report (HTTP %s): %s", status, body.strip())
        return False

    def heartbeat(self) -> bool:
        try:
            status, _ = http_request(
                "PUT", f"{self.server_url}/api/v1/agents/{self.agent_id}/heartbeat"
            )
        except ConnectionError as e:
            log.error("Failed to send heartbeat: %s", e)
            return False

        if 200 <= status < 300:
            log.info("Heartbeat sent")
            return True

        log.error("Failed to send heartbeat (HTTP %s)", status)
        return False

    # -- main loop ------------------------------------------------------------

    def _cycle(self) -> Optional[int]:
        """One check/report/heartbeat cycle; returns the next interval."""
        log.info("Starting health check cycle...")
        try:
            checker = self._checker()
        except Exception as e:
            log.error("Report generation failed: %s", e)
            return None

        report = checker.build_report()
        if self.submit_report(report):
            self.heartbeat()
        else:
            log.error("Report submission failed")

        interval = checker.get_interval()
        log.info("Next check in %s seconds", interval)
        return interval

    def run(self) -> None:
        log.info("Recur Agent started (v%s)", AGENT_VERSION)
        log.info("Configuration: %s", self.config_file)
        log.info("Server: %s", self.server_url)
        log.info("Agent ID: %s", self.agent_id)

        self.load_config()
        self.register()

        def _handle_stop(signum: int, _frame: Any) -> None:
            log.info("Received signal %s, shutting down...", signum)
            self._stop.set()

        signal.signal(signal.SIGTERM, _handle_stop)
        signal.signal(signal.SIGINT, _handle_stop)

        while not self._stop.is_set():
            if not self.registered:
                self.register()
            interval = self._cycle() or 60
            self._stop.wait(interval)

        log.info("Recur Agent stopped")

    def check_once(self) -> None:
        """Single check cycle (register + report + submit + heartbeat)."""
        self.load_config()
        self.register()
        try:
            report = self.build_report()
        except Exception as e:
            log.error("Report generation failed: %s", e)
            sys.exit(1)
        self.submit_report(report)
        self.heartbeat()

    def report(self) -> None:
        """Print the current report envelope to stdout (debugging)."""
        self.load_config()
        print(json.dumps(self.build_report(), indent=2))


################################################################################
# Entry Point
################################################################################


def main(argv: Optional[list] = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else "run"

    env_file = os.environ.get("RECUR_AGENT_ENV_FILE", ".env")
    load_env_file(env_file)
    setup_logging(os.environ.get("RECUR_AGENT_LOG_FILE", "/var/log/recur-agent.log"))

    agent = RecurAgent()

    if command == "run":
        agent.run()
    elif command == "check":
        agent.check_once()
    elif command == "register":
        agent.load_config()
        if not agent.register():
            sys.exit(1)
    elif command == "report":
        agent.report()
    else:
        print(f"Usage: {Path(sys.argv[0]).name} {{run|check|register|report}}")
        sys.exit(1)


if __name__ == "__main__":
    main()
