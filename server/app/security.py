"""
Security helpers: per-agent bearer tokens and enrollment.

Each agent receives a random token on first registration; only its SHA-256 hash is
stored in the database. Agents present the token as ``Authorization: Bearer <token>``
on every request. When ``RECUR_ENROLLMENT_TOKEN`` is configured, brand-new
registrations additionally require the pre-shared enrollment token (sent by the agent
as ``X-Recur-Enrollment-Token``); agents that already hold a valid token may
re-register/update without it.
"""

import hashlib
import hmac
import secrets
from typing import Annotated, NoReturn

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import config
from .database import get_db
from .models import Agent
from .utils.logger import get_logger

logger = get_logger(__name__)


def hash_token(token: str) -> str:
    """One-way hash stored in the database (plaintext is never persisted)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_agent_token() -> str:
    """Generate a new 256-bit agent token."""
    return secrets.token_urlsafe(32)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _bearer(request: Request) -> str | None:
    """Extract the bearer token from the Authorization header (or None)."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _reject(request: Request, detail: str) -> NoReturn:
    logger.warning(
        "Authentication failed on %s from %s: %s", request.url.path, _client_ip(request), detail
    )
    raise HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate_agent(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Agent:
    """FastAPI dependency: resolve the agent owning the presented bearer token.

    Usage: ``agent: Annotated[Agent, Depends(authenticate_agent)]``.
    """
    token = _bearer(request)
    if not token:
        _reject(request, "missing agent token (Authorization: Bearer <token>)")
    agent = db.query(Agent).filter(Agent.token_hash == hash_token(token)).first()
    if agent is None:
        _reject(request, "invalid agent token")
    return agent


def verify_enrollment(request: Request, db: Session, agent_id: str) -> bool:
    """True when the request may register or update ``agent_id``.

    Allowed when:
      - no enrollment token is configured (open registration, dev mode), or
      - the presented bearer token belongs to the agent with ``agent_id``, or
      - the presented enrollment token matches ``RECUR_ENROLLMENT_TOKEN``.
    """
    if not config.ENROLLMENT_TOKEN:
        return True

    token = _bearer(request)
    if token:
        token_hash = hash_token(token)
        owner = (
            db.query(Agent)
            .filter(Agent.agent_id == agent_id, Agent.token_hash == token_hash)
            .first()
        )
        if owner is not None:
            return True

    enrollment = request.headers.get("X-Recur-Enrollment-Token", "")
    if enrollment and hmac.compare_digest(enrollment, config.ENROLLMENT_TOKEN):
        return True

    return False


def client_ip(request: Request) -> str:
    """Client IP for audit log lines."""
    return _client_ip(request)
