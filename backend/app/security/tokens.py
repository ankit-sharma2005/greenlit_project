"""Access tokens (JWT) and opaque, hashed refresh / password-reset tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.config import Settings, get_settings

ACCESS_COOKIE = "greenlit_access"
REFRESH_COOKIE = "greenlit_refresh"
JWT_ALGORITHM = "HS256"


def utcnow() -> datetime:
    return datetime.now(UTC)


def access_token_expiry(settings: Settings) -> datetime:
    return utcnow() + timedelta(minutes=settings.access_token_expire_minutes)


def refresh_token_expiry(settings: Settings) -> datetime:
    return utcnow() + timedelta(days=settings.refresh_token_expire_days)


def password_reset_expiry(settings: Settings) -> datetime:
    return utcnow() + timedelta(minutes=settings.password_reset_expire_minutes)


def create_access_token(user_id: uuid.UUID, role: str, settings: Settings | None = None) -> str:
    """Issue a short-lived access JWT."""
    resolved = settings or get_settings()
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=resolved.access_token_expire_minutes),
    }
    return jwt.encode(payload, resolved.app_secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    """Decode and validate an access JWT; raises ``jwt.InvalidTokenError``."""
    resolved = settings or get_settings()
    payload: dict[str, Any] = jwt.decode(
        token,
        resolved.app_secret_key,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "exp", "type"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    return payload


def generate_opaque_token() -> str:
    """A high-entropy URL-safe token (refresh or password reset)."""
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of a token; only hashes are stored."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
