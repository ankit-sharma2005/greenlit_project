"""Review queue, human labels and calibration endpoints (M7).

Only reviewers and admins may label cases: a plain member can run tests but
cannot decide whether the judge was right. The guard is server-side
(:func:`app.deps.require_roles`), so the UI hiding a button is never the
protection.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.models import RunItem
from app.schemas.labels import (
    CalibrationRead,
    LabelCreate,
    LabelRead,
    ReviewCaseRead,
    ReviewQueueResponse,
)
from app.services.audit import record
from app.services.labels import LabelError, calibration, review_queue, submit_label

router = APIRouter(prefix="/api/v1/review", tags=["review"])

Reviewer = Any
reviewer_only = require_roles("reviewer", "admin")


@router.get("/queue", response_model=ReviewQueueResponse)
def get_queue(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: Reviewer = Depends(reviewer_only),
) -> ReviewQueueResponse:
    """Cases the judge could not score, was unsure about, or a label disagrees on."""
    cases = review_queue(db, user.id, limit=limit)
    return ReviewQueueResponse(
        items=[ReviewCaseRead.model_validate(case.as_dict()) for case in cases],
        total=len(cases),
    )


@router.post("/items/{run_item_id}/label", response_model=LabelRead, status_code=201)
def label_case(
    run_item_id: uuid.UUID,
    payload: LabelCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: Reviewer = Depends(reviewer_only),
) -> LabelRead:
    """Record this reviewer's verdict on one case."""
    item = db.get(RunItem, run_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    try:
        label = submit_label(db, item, user.id, payload.label, payload.note)
    except LabelError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    record(
        db,
        "review.label_submitted",
        actor_id=user.id,
        target_type="run_item",
        target_id=str(item.id),
        metadata={"label": label.label, "run_id": str(item.run_id)},
        request=request,
    )
    db.commit()
    db.refresh(label)
    return LabelRead(
        id=label.id,
        run_id=label.run_id,
        run_item_id=label.run_item_id,
        reviewer_id=label.reviewer_id,
        label=label.label,
        note=label.note,
        created_at=label.created_at,
        updated_at=label.updated_at,
    )


@router.get("/calibration", response_model=CalibrationRead)
def get_calibration(
    db: Session = Depends(get_db),
    user: Reviewer = Depends(reviewer_only),
) -> CalibrationRead:
    """Raw agreement, Cohen's kappa and a plain-language reading of both."""
    summary = calibration(db)
    return CalibrationRead.model_validate(summary.to_dict())
