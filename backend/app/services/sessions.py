"""Sessions as a person sees them: one row per refresh-token family.

The product has no "last used" column — a refresh rotates the token inside the
family — so the honest labels are the oldest token's ``created_at`` for when the
session started and the newest token's ``created_at`` for last activity. Nothing
here returns a token value, a hash or an IP address.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import RefreshToken
from app.security.tokens import utcnow
from app.services.auth import ensure_utc, find_refresh_token

UNKNOWN_DEVICE = "unknown device"
UNRECOGNISED_BROWSER = "unrecognised browser"

_BROWSERS: tuple[tuple[str, str], ...] = (
    ("edg/", "Edge"),
    ("opr/", "Opera"),
    ("chrome/", "Chrome"),
    ("firefox/", "Firefox"),
    ("safari/", "Safari"),
)

_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("windows", "Windows"),
    ("android", "Android"),
    ("iphone", "iPhone"),
    ("ipad", "iPad"),
    ("mac os", "macOS"),
    ("linux", "Linux"),
)


def describe_device(user_agent: str | None) -> str:
    """A short label from the stored user agent, or an honest "unknown device".

    A missing agent is ``unknown device``; an agent we cannot place is
    ``unrecognised browser``, which says what we know and no more.
    """
    if not user_agent or not user_agent.strip():
        return UNKNOWN_DEVICE
    agent = user_agent.lower()
    browser = next((name for needle, name in _BROWSERS if needle in agent), None)
    platform = next((name for needle, name in _PLATFORMS if needle in agent), None)
    if browser and platform:
        return f"{browser} on {platform}"
    if browser:
        return browser
    if platform:
        return platform
    return UNRECOGNISED_BROWSER


@dataclass(frozen=True)
class SessionInfo:
    """One signed-in device, reduced to what a person needs to recognise it."""

    family_id: uuid.UUID
    device: str
    created_at: datetime
    last_activity: datetime
    current: bool


def family_of(db: Session, raw_token: str) -> uuid.UUID | None:
    """The family the presented refresh token belongs to, if it is still valid."""
    stored = find_refresh_token(db, raw_token)
    return None if stored is None else stored.family_id


def list_sessions(
    db: Session, user_id: uuid.UUID, current_family_id: uuid.UUID | None = None
) -> list[SessionInfo]:
    """Every family of this user with at least one live token, newest activity first."""
    rows = db.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .order_by(RefreshToken.created_at)
    ).all()
    families: dict[uuid.UUID, list[RefreshToken]] = {}
    for row in rows:
        families.setdefault(row.family_id, []).append(row)
    now = utcnow()
    sessions: list[SessionInfo] = []
    for family_id, tokens in families.items():
        tokens.sort(key=lambda token: ensure_utc(token.created_at))
        live = [
            token
            for token in tokens
            if token.revoked_at is None and ensure_utc(token.expires_at) > now
        ]
        if not live:
            continue
        newest = tokens[-1]
        sessions.append(
            SessionInfo(
                family_id=family_id,
                device=describe_device(newest.user_agent),
                created_at=ensure_utc(tokens[0].created_at),
                last_activity=ensure_utc(newest.created_at),
                current=current_family_id is not None and family_id == current_family_id,
            )
        )
    sessions.sort(key=lambda session: session.last_activity, reverse=True)
    return sessions


def owned_family(db: Session, user_id: uuid.UUID, family_id: uuid.UUID) -> bool:
    """True when this family belongs to this user, so a foreign id cannot be touched."""
    return (
        db.scalar(
            select(RefreshToken.id).where(
                RefreshToken.user_id == user_id, RefreshToken.family_id == family_id
            )
        )
        is not None
    )


def revoke_family_of_user(db: Session, user_id: uuid.UUID, family_id: uuid.UUID) -> bool:
    """Revoke one session of this user; False when the family is not theirs."""
    if not owned_family(db, user_id, family_id):
        return False
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return True


def revoke_other_families(
    db: Session, user_id: uuid.UUID, keep_family_id: uuid.UUID | None
) -> list[uuid.UUID]:
    """Revoke every live family except the current one; returns the families revoked."""
    live = {
        session.family_id
        for session in list_sessions(db, user_id, keep_family_id)
        if session.family_id != keep_family_id
    }
    if not live:
        return []
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.family_id.in_(live),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    return sorted(live)
