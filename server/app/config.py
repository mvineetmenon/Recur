"""
Recur Server - Central Monitoring Server
FastAPI-based health check aggregator and status evaluator
"""

import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./recur.db")

# API
API_V1_PREFIX = "/api/v1"
API_TITLE = "Recur Health Monitoring API"
API_VERSION = "0.1.0"

# Server
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Timeouts and intervals
DEFAULT_CHECK_TIMEOUT = 5
MAX_CHECK_TIMEOUT = 30
MIN_CHECK_INTERVAL = 10
MAX_CHECK_INTERVAL = 3600

# Agent
AGENT_HEARTBEAT_TIMEOUT = 300  # 5 minutes
AGENT_REGISTRATION_TTL = 3600  # 1 hour

# Status retention
STATUS_RETENTION_DAYS = 30

# Pagination
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
