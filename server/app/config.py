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

# CORS: comma-separated origins; "*" allows all (dev default)
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Pagination
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
