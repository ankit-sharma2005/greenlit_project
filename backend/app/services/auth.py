"""Session and token lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import PasswordReset, RefreshToken, User
from app.security.tokens import (
    create_access_token,
    generate_opaque_token,
    hash_token,
    password_reset_expiry,
    refresh_token_expiry,
    utcnow,
)


def ensure_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; normalise so comparisons never fail."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def request_meta(request: Request) -> tuple[str | None, str | None]:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return ip_address, (user_agent[:255] if user_agent else None)


def issue_session(db: Session, user: User, request: Request, settings: Settings) -> tuple[str, str]:
    """Create an access token and a new refresh token family/session."""
    ip_address, user_agent = request_meta(request)
    raw_refresh = generate_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            family_id=uuid.uuid4(),
            expires_at=refresh_token_expiry(settings),
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    access_token = create_access_token(user.id, user.role, settings)
    return access_token, raw_refresh


def find_refresh_token(db: Session, raw_token: str) -> RefreshToken | None:
    return db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))


def revoke_token(db: Session, token: RefreshToken, replaced_by: uuid.UUID | None = None) -> None:
    token.revoked_at = utcnow()
    token.replaced_by = replaced_by


def revoke_all_for_user(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def create_password_reset(db: Session, user: User, settings: Settings) -> tuple[PasswordReset, str]:
    """Issue a fresh reset token, invalidating any previous unused ones."""
    now = utcnow()
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
        .values(used_at=now)
    )
    raw_token = generate_opaque_token()
    reset = PasswordReset(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=password_reset_expiry(settings),
    )
    db.add(reset)
    return reset, raw_token
