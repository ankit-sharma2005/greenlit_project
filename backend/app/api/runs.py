"""Run endpoints: start, read, progress, items, cancel and quick test (M6c)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Run, RunItem, User, utcnow
from app.schemas.evaluation import FailedCaseOut, MetricOut
from app.schemas.runs import (
    QuickTestRequest,
    QuickTestResponse,
    RunCreateRequest,
    RunItemRead,
    RunItemsResponse,
    RunListResponse,
    RunProgressRead,
    RunRead,
)
from app.services.audit import record
from app.services.generation import ChatFn, get_chat_fn
from app.services.run_progress import RunProgress, read_progress
from app.services.run_repository import get_metric_results, list_run_items
from app.services.run_service import (
    Enqueue,
    RunServiceError,
    cancel_run,
    create_quick_test,
    create_run_from_request,
    get_enqueue,
)

router = APIRouter(prefix="/api/v1", tags=["runs"])

ProgressReader = Callable[[uuid.UUID], RunProgress | None]


def get_progress_reader() -> ProgressReader:
    """FastAPI dependency so tests read progress without Redis."""
    return read_progress


def _service_error(exc: RunServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _owned_run(db: Session, run_id: uuid.UUID, user: User) -> Run:
    run = db.get(Run, run_id)
    if run is None or run.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; treat those as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _elapsed_seconds(run: Run) -> float | None:
    if run.started_at is None:
        return None
    finished = _aware(run.completed_at or utcnow())
    return round(max(0.0, (finished - _aware(run.started_at)).total_seconds()), 1)


def _progress(
    run: Run,
    reader: ProgressReader,
    items: Sequence[RunItem] | None = None,
) -> RunProgressRead:
    """Live counters from Redis, with the database as a fallback."""
    live = reader(run.id)
    if live is not None:
        return RunProgressRead(
            items_done=live.items_done,
            items_total=live.items_total,
            items_failed=live.items_failed,
            items_cancelled=live.items_cancelled,
            stage=live.stage,
            started_at=live.started_at,
            updated_at=live.updated_at,
            elapsed_seconds=_elapsed_seconds(run),
        )
    if items is None:
        return RunProgressRead(stage=run.state, elapsed_seconds=_elapsed_seconds(run))
    finished = [item for item in items if item.state in ("completed", "failed", "cancelled")]
    return RunProgressRead(
        items_done=len(finished),
        items_total=len(items),
        items_failed=sum(1 for item in items if item.state == "failed"),
        items_cancelled=sum(1 for item in items if item.state == "cancelled"),
        stage=run.state,
        started_at=run.started_at.isoformat() if run.started_at else None,
        updated_at=utcnow().isoformat(),
        elapsed_seconds=_elapsed_seconds(run),
    )


def _run_read(
    db: Session,
    run: Run,
    reader: ProgressReader,
    *,
    detail: bool = False,
) -> RunRead:
    items = list_run_items(db, run.id) if detail else None
    snapshot = dict(run.settings_snapshot or {})
    test_types = [str(value) for value in snapshot.get("test_types") or []]
    metrics: list[MetricOut] = []
    failures: list[FailedCaseOut] = []
    if detail:
        for row in get_metric_results(db, run.id):
            metrics.append(
                MetricOut(
                    name=row.name,
                    score=row.score,
                    passed=row.passed,
                    explanation=row.explanation,
                    instrumented=row.instrumented,
                    weight=row.weight,
                    threshold=row.threshold,
                    hard_gate=row.hard_gate,
                    details=dict(row.details or {}),
                )
            )
        for item in items or []:
            if item.state != "failed":
                continue
            failures.append(
                FailedCaseOut(
                    input=item.input_text,
                    expected="",
                    actual=item.output or "",
                    reason=item.error or "The app did not answer this case.",
                )
            )
    return RunRead(
        id=run.id,
        name=run.name,
        entry_point=str(snapshot.get("entry_point") or "http_endpoint"),
        state=run.state,
        verdict=run.verdict,
        score=run.score,
        verdict_reason=run.verdict_reason,
        is_partial=run.is_partial,
        criteria_profile=run.criteria_profile,
        test_types=test_types,
        dataset_id=run.dataset_id,
        dataset_version_id=run.dataset_version_id,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        progress=_progress(run, reader, items),
        metrics=metrics,
        failed_cases=failures,
    )


@router.post("/runs", response_model=RunRead, status_code=202)
def start_run(
    payload: RunCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
    enqueue: Enqueue = Depends(get_enqueue),
    reader: ProgressReader = Depends(get_progress_reader),
) -> RunRead:
    """Queue a run; it executes in the worker, never inside this request."""
    try:
        run = create_run_from_request(db, user, payload, enqueue)
    except RunServiceError as exc:
        db.rollback()
        raise _service_error(exc) from exc
    record(
        db,
        "run.start",
        actor_id=user.id,
        target_type="run",
        target_id=str(run.id),
        metadata={
            "entry_point": payload.entry_point,
            "test_types": list(payload.test_types),
            "criteria_profile": run.criteria_profile,
        },
        request=request,
    )
    db.commit()
    return _run_read(db, run, reader)


@router.post("/quick-test", response_model=QuickTestResponse, status_code=202)
def quick_test(
    payload: QuickTestRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
    enqueue: Enqueue = Depends(get_enqueue),
    reader: ProgressReader = Depends(get_progress_reader),
    chat: ChatFn = Depends(get_chat_fn),
) -> QuickTestResponse:
    """Create connector, dataset and run from one request (spec section 9)."""
    try:
        run, version, generated = create_quick_test(db, user, payload, enqueue, chat)
    except RunServiceError as exc:
        db.rollback()
        raise _service_error(exc) from exc
    record(
        db,
        "run.start",
        actor_id=user.id,
        target_type="run",
        target_id=str(run.id),
        metadata={
            "entry_point": payload.entry_point,
            "test_types": list(payload.tests),
            "dataset_version_id": str(version.id),
            "generated_cases": generated,
            "quick_test": True,
        },
        request=request,
    )
    db.commit()
    return QuickTestResponse(
        run=_run_read(db, run, reader),
        dataset_id=version.dataset_id,
        dataset_version_id=version.id,
        generated=generated,
    )


@router.get("/runs", response_model=RunListResponse)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
    reader: ProgressReader = Depends(get_progress_reader),
) -> RunListResponse:
    total = db.scalar(select(func.count()).select_from(Run).where(Run.owner_id == user.id)) or 0
    rows = (
        db.execute(
            select(Run)
            .where(Run.owner_id == user.id)
            .order_by(Run.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return RunListResponse(
        items=[_run_read(db, run, reader) for run in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
    reader: ProgressReader = Depends(get_progress_reader),
) -> RunRead:
    return _run_read(db, _owned_run(db, run_id, user), reader, detail=True)


@router.get("/runs/{run_id}/progress", response_model=RunProgressRead)
def get_run_progress(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
    reader: ProgressReader = Depends(get_progress_reader),
) -> RunProgressRead:
    run = _owned_run(db, run_id, user)
    return _progress(run, reader, list_run_items(db, run.id))


@router.get("/runs/{run_id}/items", response_model=RunItemsResponse)
def get_run_items(
    run_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> RunItemsResponse:
    run = _owned_run(db, run_id, user)
    items = list_run_items(db, run.id)
    window = items[offset : offset + limit]
    return RunItemsResponse(
        items=[
            RunItemRead(
                row_index=item.row_index,
                input_text=item.input_text,
                state=item.state,
                output=item.output,
                error=item.error,
                latency_ms=item.latency_ms,
                tokens_in=item.tokens_in,
                tokens_out=item.tokens_out,
                trace=item.trace,
            )
            for item in window
        ],
        total=len(items),
    )


@router.post("/runs/{run_id}/cancel", response_model=RunRead)
def cancel(
    run_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
    reader: ProgressReader = Depends(get_progress_reader),
) -> RunRead:
    run = _owned_run(db, run_id, user)
    try:
        cancel_run(db, run)
    except RunServiceError as exc:
        db.rollback()
        raise _service_error(exc) from exc
    record(
        db,
        "run.cancel",
        actor_id=user.id,
        target_type="run",
        target_id=str(run.id),
        metadata={"state": run.state},
        request=request,
    )
    db.commit()
    db.refresh(run)
    return _run_read(db, run, reader, detail=True)
