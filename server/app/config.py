"""
Recur Server - Central Monitoring Server
FastAPI-based health check aggregator and status evaluator
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env-style configuration for standalone runs (in docker mode the
# compose file passes explicit environment variables instead). Existing
# environment variables always take precedence over .env values.
load_dotenv(BASE_DIR.parent / ".env")  # repo root, independent of the CWD
load_dotenv(Path.cwd() / ".env")  # current working directory (other layouts)

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = BASE_DIR / "logs"

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./recur.db")

# API
API_V1_PREFIX = "/api/v1"
API_TITLE = "Recur Health Monitoring API"
API_VERSION = "0.1.0"

# Server
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
# Standalone default is loopback: put a reverse proxy in front for network
# access. Docker mode sets HOST=0.0.0.0 explicitly (see docker-compose.yml).
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# CORS: comma-separated origins; empty (default) disables the CORS middleware
# entirely. The dashboard is served same-origin, so it needs no CORS.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

# Security
# Pre-shared token required for NEW agent registrations when set. Agents that
# already hold a valid token can re-register without it. When empty,
# registration is open (dev mode) and each open registration logs a warning.
ENROLLMENT_TOKEN = os.getenv("RECUR_ENROLLMENT_TOKEN", "")

# Pagination
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
