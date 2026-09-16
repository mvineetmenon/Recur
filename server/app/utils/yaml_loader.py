"""
Utilities for YAML configuration loading and parsing
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class YAMLConfigError(Exception):
    """Raised when YAML config is invalid"""

    pass


def load_yaml_file(path: str | Path) -> Dict[str, Any]:
    """
    Load and parse a YAML configuration file

    Args:
        path: Path to YAML file

    Returns:
        Parsed YAML as dictionary

    Raises:
        YAMLConfigError: If file doesn't exist or is invalid
    """
    path = Path(path)

    if not path.exists():
        raise YAMLConfigError(f"Config file not found: {path}")

    try:
        with open(path, "r") as f:
            config = yaml.safe_load(f)

        if config is None:
            raise YAMLConfigError("Config file is empty")

        return config
    except yaml.YAMLError as e:
        raise YAMLConfigError(f"Failed to parse YAML: {e}")
    except IOError as e:
        raise YAMLConfigError(f"Failed to read config file: {e}")


def validate_system_config(config: Dict[str, Any]) -> None:
    """
    Validate system configuration structure

    Args:
        config: Configuration dictionary

    Raises:
        YAMLConfigError: If config structure is invalid
    """
    if "system" not in config:
        raise YAMLConfigError("Config must have 'system' root key")

    system = config["system"]

    # Required fields
    if "name" not in system:
        raise YAMLConfigError("System must have 'name'")

    if "tasks" in system:
        tasks = system["tasks"]
        if not isinstance(tasks, list):
            raise YAMLConfigError("'tasks' must be a list")

        for i, task in enumerate(tasks):
            if "type" not in task:
                raise YAMLConfigError(f"Task {i} missing 'type'")

            task_type = task["type"]
            valid_types = {"http", "https", "tcp", "command", "ping", "script"}
            if task_type not in valid_types:
                raise YAMLConfigError(
                    f"Task {i} has invalid type '{task_type}'. "
                    f"Must be one of: {', '.join(valid_types)}"
                )


def validate_task_type_config(task: Dict[str, Any]) -> None:
    """
    Validate task configuration based on type

    Args:
        task: Task configuration

    Raises:
        YAMLConfigError: If task config is invalid for its type
    """
    task_type = task.get("type", "").lower()

    if task_type in ("http", "https"):
        if "url" not in task:
            raise YAMLConfigError("HTTP/HTTPS task missing 'url'")
        # A missing expected_status is fine: the agent defaults to 200

    elif task_type == "tcp":
        if "host" not in task or "port" not in task:
            raise YAMLConfigError("TCP task missing 'host' or 'port'")

    elif task_type == "command":
        if "command" not in task:
            raise YAMLConfigError("Command task missing 'command'")

    elif task_type == "ping":
        if "host" not in task:
            raise YAMLConfigError("Ping task missing 'host'")

    elif task_type == "script":
        if "path" not in task:
            raise YAMLConfigError("Script task missing 'path'")


def flatten_config(config: Dict[str, Any], parent_key: str = "") -> Dict[str, Dict[str, Any]]:
    """
    Flatten hierarchical system config into task map

    Args:
        config: Configuration dictionary
        parent_key: Key of parent system

    Returns:
        Flat dictionary of {system_id: system_config}
    """
    systems = {}

    def _traverse(node: Dict[str, Any], parent_id: Optional[str] = None) -> str:
        """Recursively traverse and flatten system tree"""
        system_id = node.get("id") or node.get("name", "").lower().replace(" ", "-")

        systems[system_id] = {
            "name": node.get("name"),
            "description": node.get("description"),
            "interval": node.get("interval", 60),
            "tasks": node.get("tasks", []),
            "parent_id": parent_id,
        }

        # Process dependencies
        for dep in node.get("dependencies", []):
            _traverse(dep, parent_id=system_id)

        return system_id

    if "system" in config:
        _traverse(config["system"])

    return systems


def config_to_json_serializable(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert config to JSON-serializable format (for database storage)

    Args:
        config: Configuration dictionary

    Returns:
        JSON-serializable configuration
    """
    return json.loads(json.dumps(config, default=str))
