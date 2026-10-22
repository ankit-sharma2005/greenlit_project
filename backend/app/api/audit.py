"""Append-only audit log (admin only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
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
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AuditListResponse:
    """Newest first."""
    total = db.scalar(select(func.count()).select_from(AuditEvent)) or 0
    events = db.scalars(
        select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return AuditListResponse(
        items=[AuditEventRead.model_validate(event) for event in events],
        total=total,
        limit=limit,
        offset=offset,
    )
