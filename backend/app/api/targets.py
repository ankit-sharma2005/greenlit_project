"""The target check: one harmless request before a full run (STEP 2).

Two endpoints, both authenticated and owner-scoped: run a check, then accept the
extraction it read. The check never creates a run and never stores the answer;
the accept step is what a full run on a remote target requires.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.schemas.targets import TargetCheckRequest, TargetCheckResponse
from app.services import target_check
from app.services.audit import record
from app.services.run_service import RunServiceError, build_snapshot
from app.services.target_error import target_of

router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


def _run_service_error(exc: RunServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _check_error(exc: target_check.TargetCheckError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _read(check: target_check.TargetCheck) -> TargetCheckResponse:
    """The stored result as the API returns it (never a header value)."""
    return TargetCheckResponse(
        check_id=check.id,
        expires_at=datetime.fromtimestamp(check.expires_at, tz=UTC),
        accepted=check.accepted,
        **check.result,
    )


@router.post("/check", response_model=TargetCheckResponse)
def check_target(
    payload: TargetCheckRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> TargetCheckResponse:
    """Send exactly one harmless request and show what GreenLit reads back."""
    try:
        # The run's own snapshot rules: URL shape, SSRF/private check and the
        # permission record are the ones a run would apply.
        snapshot = build_snapshot(
            payload.to_run_request(), dataset_version_id=None, entry_point="http_endpoint"
        )
    except RunServiceError as exc:
        raise _run_service_error(exc) from exc

    input_text, _column = target_check.first_case_input(db, user, payload.dataset_version_id)
    try:
        outcome = target_check.run_check(snapshot, input_text=input_text)
    except RunServiceError as exc:  # a connector that cannot be built
        raise _run_service_error(exc) from exc
    check = target_check.record_check(
        owner_id=user.id,
        config_hash=target_check.fingerprint(snapshot),
        result={
            "request": outcome.request,
            "status": outcome.status,
            "latency_ms": outcome.latency_ms,
            "answer": outcome.answer,
            "answer_truncated": outcome.answer_truncated,
            "extraction_ok": outcome.extraction_ok,
            "mapping_path": outcome.mapping_path,
            "hint": outcome.hint,
            "error": outcome.error,
        },
    )
    record(
        db,
        "target.check",
        actor_id=user.id,
        target_type="target",
        target_id=target_of(str(snapshot.get("url") or "")),
        metadata={
            "check_id": check.id,
            "status": outcome.status,
            # The kind only: the snippet and the answer stay out of the audit log.
            "error_kind": (outcome.error or {}).get("kind"),
            "permission_confirmed": bool(snapshot.get("permission_confirmed")),
            "permission_reference": snapshot.get("permission_reference"),
        },
        request=request,
    )
    db.commit()
    return _read(check)


@router.post("/check/{check_id}/accept", response_model=TargetCheckResponse)
def accept_target_check(
    check_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> TargetCheckResponse:
    """The person confirmed this extraction, so a full run may start."""
    try:
        check = target_check.accept_check(check_id, user.id)
    except target_check.TargetCheckError as exc:
        raise _check_error(exc) from exc
    record(
        db,
        "target.check_accepted",
        actor_id=user.id,
        target_type="target",
        target_id=str((check.result.get("request") or {}).get("url") or ""),
        metadata={"check_id": check.id},
        request=request,
    )
    db.commit()
    return _read(check)
