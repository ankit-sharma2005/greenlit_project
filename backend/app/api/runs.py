"""Run endpoints: start, read, progress, items, cancel and quick test (M6c)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Provider, Run, RunBaseline, RunItem, User, utcnow
from app.schemas.evaluation import FailedCaseOut, MetricOut
from app.schemas.runs import (
    BaselineCreate,
    BaselineRead,
    OperationsRead,
    QuickTestRequest,
    QuickTestResponse,
    RegressionRead,
    RunCreateRequest,
    RunItemRead,
    RunItemsResponse,
    RunJudgeRead,
    RunLimitsRead,
    RunListResponse,
    RunPermissionRead,
    RunProgressRead,
    RunRead,
)
from app.services.audit import record
from app.services.generation import ChatFn, get_chat_fn
from app.services.operations import (
    compute_operations,
    prices_from_metadata,
    samples_from_items,
)
from app.services.regression import (
    RegressionError,
    baseline_for_run,
    regression_for,
)
from app.services.regression import (
    clear_baseline as clear_run_baseline,
)
from app.services.regression import (
    set_baseline as set_run_baseline,
)
from app.services.report import build_report, render
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


def _text_or_none(value: object) -> str | None:
    """A JSON value as display text, or None when it is missing or not scalar."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _optional_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _limits_read(snapshot: dict[str, Any]) -> RunLimitsRead | None:
    """The caps the run carried, and which one stopped it (quirk 14)."""
    raw_stop = snapshot.get("limit_stop")
    stop = raw_stop if isinstance(raw_stop, dict) else {}
    limits = RunLimitsRead(
        max_cases=_optional_count(snapshot.get("max_cases")),
        max_duration_seconds=_optional_count(snapshot.get("max_duration_seconds")),
        max_total_tokens=_optional_count(snapshot.get("max_total_tokens")),
        stopped_by=_text_or_none(stop.get("kind")),
        stop_reason=_text_or_none(stop.get("detail")),
        tokens_not_instrumented=bool(snapshot.get("tokens_not_instrumented")),
    )
    if (
        limits.max_cases is None
        and limits.max_duration_seconds is None
        and limits.max_total_tokens is None
        and limits.stopped_by is None
    ):
        # A run from before caps existed carries no limits block at all.
        return None
    return limits


def _permission_read(snapshot: dict[str, Any]) -> RunPermissionRead | None:
    """The permission recorded with the run; absent for a local app."""
    if "permission_confirmed" not in snapshot:
        return None
    reference = snapshot.get("permission_reference")
    return RunPermissionRead(
        confirmed=bool(snapshot.get("permission_confirmed")),
        reference=str(reference) if reference else None,
        safety_attacks_confirmed=bool(snapshot.get("safety_attacks_confirmed")),
    )


def _judge_read(
    snapshot: dict[str, Any],
) -> RunJudgeRead | None:
    """The judge provenance the worker stored, or None when no judge ran."""
    raw = snapshot.get("judge")
    if not isinstance(raw, dict):
        return None
    temperature = raw.get("judge_temperature")
    max_tokens = raw.get("judge_max_tokens")
    return RunJudgeRead(
        model=_text_or_none(raw.get("judge_model")),
        provider_name=_text_or_none(raw.get("judge_provider_name")),
        profile_name=_text_or_none(raw.get("judge_profile_name")),
        rubric_version=_text_or_none(raw.get("judge_rubric_version")),
        prompt_template_hash=_text_or_none(raw.get("judge_prompt_hash")),
        temperature=float(temperature) if isinstance(temperature, (int, float)) else None,
        max_tokens=_count(max_tokens) if max_tokens is not None else None,
        max_cases=_count(raw.get("judge_max_cases")) if raw.get("judge_max_cases") else None,
        case_total=_count(raw.get("judge_case_total")),
        capped_items=_count(raw.get("judge_capped_items")),
        graded_items=_count(raw.get("judge_graded_items")),
        unavailable_items=_count(raw.get("judge_unavailable_items")),
        low_confidence_items=_count(raw.get("judge_low_confidence_items")),
    )


def _baseline_read(db: Session, baseline: RunBaseline) -> BaselineRead:
    """A stored baseline plus the run's name, which is what the UI shows."""
    baseline_run = db.get(Run, baseline.run_id)
    return BaselineRead(
        run_id=baseline.run_id,
        run_name=baseline_run.name if baseline_run is not None else None,
        dataset_id=baseline.dataset_id,
        dataset_version_id=baseline.dataset_version_id,
        metric_tolerance=baseline.metric_tolerance,
        case_tolerance=baseline.case_tolerance,
        is_active=baseline.is_active,
        created_at=baseline.created_at,
        updated_at=baseline.updated_at,
    )


def _regression_read(
    db: Session, run: Run, snapshot: dict[str, Any]
) -> tuple[dict[str, Any] | None, bool]:
    """The comparison for this run, and whether the run is the baseline itself.

    The worker stores the comparison when the run finishes. It is recomputed here
    only when the baseline has been changed since, so the card never shows a
    comparison against a run that is no longer the baseline.
    """
    if snapshot.get("is_smoke"):
        # A rehearsal is compared with nothing and can never be a baseline.
        return None, False
    baseline = baseline_for_run(db, run)
    if baseline is None:
        return None, False
    is_baseline = baseline.run_id == run.id
    if is_baseline or run.state != "completed":
        return None, is_baseline
    stored = snapshot.get("regression")
    if isinstance(stored, dict) and stored.get("baseline_run_id") == str(baseline.run_id):
        return stored, False
    fresh = regression_for(db, run)
    return (fresh.as_dict() if fresh is not None else None), False


def _operations_read(
    db: Session,
    run: Run,
    items: Sequence[RunItem] | None,
) -> dict[str, Any] | None:
    """The run's operations block: the stored one, else computed, else nothing.

    Older runs predate the stored column, so a detail read recomputes it from the
    cases it already loaded. Prices come from the provider's metadata settings;
    when they are absent the cost estimate stays null and the UI says so.
    """
    if run.operations is not None:
        return dict(run.operations)
    if items is None:
        return None

    snapshot = dict(run.settings_snapshot or {})
    price_in: float | None = None
    price_out: float | None = None
    raw_id = snapshot.get("provider_id")
    if isinstance(raw_id, str) and raw_id:
        try:
            provider = db.get(Provider, uuid.UUID(raw_id))
        except ValueError:
            provider = None
        if provider is not None:
            price_in, price_out = prices_from_metadata(provider.provider_config)

    return compute_operations(
        samples_from_items(items),
        price_per_1k_tokens_in=price_in,
        price_per_1k_tokens_out=price_out,
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
            meta = item.trace if isinstance(item.trace, dict) else {}
            raw_failure = meta.get("error_detail")
            failure = raw_failure if isinstance(raw_failure, dict) else {}
            status = failure.get("status")
            failures.append(
                FailedCaseOut(
                    input=item.input_text,
                    expected="",
                    actual=item.output or "",
                    reason=item.error or "The app did not answer this case.",
                    error_kind=str(failure.get("kind") or meta.get("error_kind") or "") or None,
                    http_status=status if isinstance(status, int) else None,
                    target=str(failure.get("target") or "") or None,
                    error_snippet=str(failure.get("snippet") or "") or None,
                    error_summary=str(failure.get("summary") or "") or None,
                )
            )
    regression_payload, is_baseline = _regression_read(db, run, snapshot)
    operations_payload = _operations_read(db, run, items)
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
        permission=_permission_read(snapshot),
        dataset_id=run.dataset_id,
        dataset_version_id=run.dataset_version_id,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        progress=_progress(run, reader, items),
        metrics=metrics,
        failed_cases=failures,
        judge=_judge_read(snapshot),
        judge_skipped_reason=_text_or_none(snapshot.get("judge_skipped_reason")),
        regression=(
            RegressionRead.model_validate(regression_payload)
            if regression_payload is not None
            else None
        ),
        is_baseline=is_baseline,
        limits=_limits_read(snapshot),
        is_smoke=bool(snapshot.get("is_smoke")),
        operations=(
            OperationsRead.model_validate(operations_payload)
            if operations_payload is not None
            else None
        ),
    )


@router.post("/runs", response_model=RunRead, status_code=202)
def start_run(
    payload: RunCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
    enqueue: Enqueue = Depends(get_enqueue),
    reader: ProgressReader = Depends(get_progress_reader),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunRead:
    """Queue a run; it executes in the worker, never inside this request.

    An ``Idempotency-Key`` makes a retried start return the run it already
    created instead of sending every case a second time (quirk 13).
    """
    try:
        run = create_run_from_request(
            db, user, payload, enqueue, idempotency_key=idempotency_key, dedupe=True
        )
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
            # Who allowed testing this target, when it was not the user's own app.
            "permission_confirmed": bool(run.settings_snapshot.get("permission_confirmed")),
            "permission_reference": run.settings_snapshot.get("permission_reference"),
            "safety_attacks_confirmed": bool(run.settings_snapshot.get("safety_attacks_confirmed")),
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
            "permission_confirmed": bool(run.settings_snapshot.get("permission_confirmed")),
            "permission_reference": run.settings_snapshot.get("permission_reference"),
            "safety_attacks_confirmed": bool(run.settings_snapshot.get("safety_attacks_confirmed")),
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


@router.get("/runs/{run_id}/report")
def get_run_report(
    run_id: uuid.UUID,
    format: str = Query(default="html", pattern="^(html|json|csv)$"),
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> Response:
    """Export one run (spec 8.5): self-contained HTML, full JSON or case-level CSV.

    Owner-scoped like every other run endpoint, and secret-free by construction:
    the report service redacts request headers and never touches provider keys.
    """
    run = _owned_run(db, run_id, user)
    body, media_type, extension = render(build_report(db, run), format)
    filename = f"greenlit-run-{run.id}.{extension}"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@router.get("/runs/{run_id}/baseline", response_model=BaselineRead | None)
def get_baseline(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> BaselineRead | None:
    """The baseline for this run's dataset version, or null when none is set."""
    run = _owned_run(db, run_id, user)
    baseline = baseline_for_run(db, run)
    return _baseline_read(db, baseline) if baseline is not None else None


@router.post("/runs/{run_id}/baseline", response_model=BaselineRead, status_code=201)
def set_baseline(
    run_id: uuid.UUID,
    payload: BaselineCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> BaselineRead:
    """Make this completed run the baseline for its dataset version (spec 8.5)."""
    run = _owned_run(db, run_id, user)
    try:
        baseline = set_run_baseline(
            db,
            run,
            metric_tolerance=payload.metric_tolerance,
            case_tolerance=payload.case_tolerance,
        )
    except RegressionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    record(
        db,
        "run.baseline_set",
        actor_id=user.id,
        target_type="run",
        target_id=str(run.id),
        metadata={
            "metric_tolerance": payload.metric_tolerance,
            "case_tolerance": payload.case_tolerance,
        },
        request=request,
    )
    db.commit()
    db.refresh(baseline)
    return _baseline_read(db, baseline)


@router.delete("/runs/{run_id}/baseline", status_code=204)
def clear_baseline(
    run_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: Any = Depends(get_current_user),
) -> Response:
    """Stop comparing against this dataset version's baseline."""
    run = _owned_run(db, run_id, user)
    removed = clear_run_baseline(db, run)
    if not removed:
        raise HTTPException(status_code=404, detail="This dataset version has no baseline.")
    record(
        db,
        "run.baseline_cleared",
        actor_id=user.id,
        target_type="run",
        target_id=str(run.id),
        request=request,
    )
    db.commit()
    return Response(status_code=204)
