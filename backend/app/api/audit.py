"""Append-only audit log (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_admin
from app.models import AuditEvent, User
from app.schemas.audit import AuditEventRead, AuditListResponse

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
def list_audit_events(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, max_length=80),
    target_type: str | None = Query(default=None, max_length=40),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AuditListResponse:
    """Newest first, with an optional action/target filter for the audit screen."""
    filters: list[ColumnElement[bool]] = []
    if action:
        filters.append(AuditEvent.action.ilike(f"%{action}%"))
    if target_type:
        filters.append(AuditEvent.target_type == target_type)
    query = select(AuditEvent)
    count_query = select(func.count()).select_from(AuditEvent)
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = db.scalar(count_query) or 0
    events = db.scalars(
        query.order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return AuditListResponse(
        items=[AuditEventRead.model_validate(event) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )
