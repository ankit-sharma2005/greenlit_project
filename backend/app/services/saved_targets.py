"""Saved target services (M13).

The Settings → Connectors panel keeps the connectors a person actually tests. A
saved target holds only what describes the app: URL, method, body template, the
answer/context paths and the polite-rate settings. It deliberately never holds a
header value — a pasted cURL's headers stay encrypted inside the run that used
them — and it never holds a permission record, which the first-contact check
(STEP 2) asks for per run.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SavedTarget

MAX_HEADER_NAMES = 60


class SavedTargetError(Exception):
    """A refusal the API turns into an HTTP error with a message people can act on."""

    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _clean_name(name: str | None) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise SavedTargetError("Enter a name for this target, such as “Support bot”.")
    if len(cleaned) > 120:
        raise SavedTargetError("The name can be at most 120 characters.")
    return cleaned


def _clean_url(url: str | None) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise SavedTargetError("Enter the URL of the app this target points at.")
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SavedTargetError(
            "That URL is not a full http(s) address. It should look like "
            "https://myapp.example.com/ask."
        )
    return cleaned


def _clean_method(method: str | None) -> str:
    cleaned = (method or "").strip().upper() or "POST"
    if len(cleaned) > 10:
        raise SavedTargetError("The HTTP method can be at most 10 characters.")
    return cleaned


def _clean_path(path: str | None) -> str | None:
    cleaned = (path or "").strip()
    return cleaned or None


def _clean_body(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _clean_header_names(names: Sequence[str] | None) -> list[str]:
    """Header names only, de-duplicated and in the order they are sent."""
    cleaned: list[str] = []
    for raw in names or []:
        name = str(raw).strip()
        if name and name not in cleaned:
            cleaned.append(name)
    if len(cleaned) > MAX_HEADER_NAMES:
        raise SavedTargetError(f"A request can carry at most {MAX_HEADER_NAMES} headers.")
    return cleaned


def _duplicate_name(
    db: Session, owner_id: uuid.UUID, name: str, *, exclude: uuid.UUID | None = None
) -> bool:
    statement = select(SavedTarget.id).where(
        SavedTarget.owner_id == owner_id, SavedTarget.name == name
    )
    if exclude is not None:
        statement = statement.where(SavedTarget.id != exclude)
    return db.scalar(statement) is not None


def create_saved_target(
    db: Session,
    *,
    owner_id: uuid.UUID,
    name: str,
    url: str,
    method: str = "POST",
    body_template: str | None = None,
    header_names: Sequence[str] | None = None,
    answer_path: str | None = None,
    context_path: str | None = None,
    stream_content_path: str | None = None,
    response_format: str = "json",
    timeout_seconds: int = 60,
    max_concurrency: int = 1,
    min_delay_ms: int = 500,
    max_retries: int = 3,
    allow_private_targets: bool = False,
) -> SavedTarget:
    """Save one target for this owner; a repeated name is a 409, not a guess."""
    clean_name = _clean_name(name)
    if _duplicate_name(db, owner_id, clean_name):
        raise SavedTargetError(
            f"You already saved a target named “{clean_name}”. Pick another name.",
            status=409,
        )
    target = SavedTarget(
        owner_id=owner_id,
        name=clean_name,
        connector_type="http_endpoint",
        url=_clean_url(url),
        method=_clean_method(method),
        body_template=_clean_body(body_template),
        header_names=_clean_header_names(header_names),
        answer_path=_clean_path(answer_path),
        context_path=_clean_path(context_path),
        stream_content_path=_clean_path(stream_content_path),
        response_format=response_format,
        timeout_seconds=timeout_seconds,
        max_concurrency=max_concurrency,
        min_delay_ms=min_delay_ms,
        max_retries=max_retries,
        allow_private_targets=allow_private_targets,
    )
    db.add(target)
    db.flush()
    return target


def list_saved_targets(db: Session, owner_id: uuid.UUID) -> list[SavedTarget]:
    """The owner's targets, oldest first, so the list order is stable."""
    statement = (
        select(SavedTarget)
        .where(SavedTarget.owner_id == owner_id)
        .order_by(SavedTarget.created_at, SavedTarget.id)
    )
    return list(db.scalars(statement).all())


def get_saved_target(
    db: Session, target_id: uuid.UUID, *, owner_id: uuid.UUID
) -> SavedTarget | None:
    """One target, or None when it belongs to somebody else (the API answers 404)."""
    statement = select(SavedTarget).where(
        SavedTarget.id == target_id, SavedTarget.owner_id == owner_id
    )
    return db.scalar(statement)


def update_saved_target(db: Session, target: SavedTarget, **changes: Any) -> SavedTarget:
    """Apply the fields the client sent, validating them the way creation does."""
    if "name" in changes:
        clean_name = _clean_name(changes["name"])
        if _duplicate_name(db, target.owner_id, clean_name, exclude=target.id):
            raise SavedTargetError(
                f"You already saved a target named “{clean_name}”. Pick another name.",
                status=409,
            )
        target.name = clean_name
    if "url" in changes:
        target.url = _clean_url(changes["url"])
    if "method" in changes:
        target.method = _clean_method(changes["method"])
    if "body_template" in changes:
        target.body_template = _clean_body(changes["body_template"])
    if "header_names" in changes:
        target.header_names = _clean_header_names(changes["header_names"])
    if "answer_path" in changes:
        target.answer_path = _clean_path(changes["answer_path"])
    if "context_path" in changes:
        target.context_path = _clean_path(changes["context_path"])
    if "stream_content_path" in changes:
        target.stream_content_path = _clean_path(changes["stream_content_path"])
    for field in (
        "response_format",
        "timeout_seconds",
        "max_concurrency",
        "min_delay_ms",
        "max_retries",
        "allow_private_targets",
    ):
        if field in changes and changes[field] is not None:
            setattr(target, field, changes[field])
    db.flush()
    return target


def delete_saved_target(db: Session, target: SavedTarget) -> None:
    """Remove a target; runs keep their own snapshot, so history is unaffected."""
    db.delete(target)
    db.flush()
