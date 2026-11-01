"""Run lifecycle: snapshot settings, queue the worker, cancel (M6c).

The API never executes a test: it validates the request, stores the settings
snapshot, creates the run and hands the id to Celery (spec 8.1). Cancelling
flips the state and lets the executor stop at its next case boundary; a queued
run is cancelled directly, so a late worker task just skips it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, DatasetVersion, Provider, Run, RunState, User, utcnow
from app.safety.sets import SafetySelection, SafetySetError, resolve_safety_sets
from app.schemas.runs import QuickTestRequest, RunCreateRequest
from app.services.criteria import CriteriaError, get_profile
from app.services.datasets import (
    DatasetError,
    approve_dataset_version,
    create_dataset,
)
from app.services.generation import ChatFn, GenerationError, generate_test_cases
from app.services.judge_profiles import get_judge_profile, selected_judge_profile
from app.services.run_repository import create_run

Enqueue = Callable[[uuid.UUID], None]

_DEFAULT_BODY_TEMPLATE = '{"question": {{input}}}'


class RunServiceError(ValueError):
    """A run cannot be created or cancelled; ``status`` maps to the HTTP code."""

    def __init__(self, message: str, *, status: int = 400, code: str = "bad_request") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def enqueue_run(run_id: uuid.UUID) -> None:
    """Hand one run to the Celery worker (never executed in the request)."""
    from app.tasks import run_test

    run_test.delay(str(run_id))


def get_enqueue() -> Enqueue:
    """FastAPI dependency so tests can queue without a broker."""
    return enqueue_run


def _check_url(target: str | None) -> str:
    url = (target or "").strip()
    if not url:
        raise RunServiceError("Enter the URL of the app GreenLit should test, then start again.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RunServiceError(
            "That URL is not a full http(s) address. It should look like "
            "https://myapp.example.com/ask."
        )
    return url


def resolve_criteria_profile(name: str | None, snapshot: Mapping[str, Any]) -> str:
    """Explicit profile, else RAG chatbot when context was detected, else plain."""
    if name:
        try:
            return get_profile(name).key
        except CriteriaError as exc:
            raise RunServiceError(exc.message, status=400) from exc
    return "rag_chatbot" if snapshot.get("context_path") else "plain_chatbot"


def _approved_version(
    session: Session,
    user: User,
    *,
    dataset_id: uuid.UUID | None,
    dataset_version_id: uuid.UUID | None,
) -> tuple[Dataset, DatasetVersion]:
    """The newest approved version of the owner's dataset, or a friendly error."""
    dataset: Dataset | None = None
    if dataset_id is not None:
        dataset = session.get(Dataset, dataset_id)
        if dataset is None or dataset.owner_id != user.id:
            raise RunServiceError(
                "That dataset was not found. Pick one from Settings > Datasets.",
                status=404,
                code="not_found",
            )
    if dataset_version_id is not None:
        version = session.get(DatasetVersion, dataset_version_id)
        if version is None:
            raise RunServiceError(
                "That dataset version was not found. Pick the dataset again.",
                status=404,
                code="not_found",
            )
        owner_dataset = session.get(Dataset, version.dataset_id)
        if owner_dataset is None or owner_dataset.owner_id != user.id:
            raise RunServiceError(
                "That dataset was not found. Pick one from Settings > Datasets.",
                status=404,
                code="not_found",
            )
        dataset = owner_dataset
        if version.approved_at is None:
            raise RunServiceError(
                "That dataset version is not approved yet. "
                "Approve it in Settings > Datasets, then start the run."
            )
        return dataset, version
    if dataset is None:
        raise RunServiceError("Choose a dataset first, or upload one in Settings > Datasets.")
    versions = session.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.version_no.desc())
    ).all()
    approved = [candidate for candidate in versions if candidate.approved_at is not None]
    if not approved:
        raise RunServiceError(
            "This dataset has no approved version. "
            "Approve one in Settings > Datasets, then start the run."
        )
    return dataset, approved[0]


def build_snapshot(
    payload: RunCreateRequest,
    *,
    dataset_version_id: uuid.UUID,
    entry_point: str,
) -> dict[str, Any]:
    """The settings a queued run executes with (never read live again)."""
    snapshot: dict[str, Any] = {
        "entry_point": entry_point,
        "test_types": list(payload.test_types),
        "dataset_version_id": str(dataset_version_id),
        "timeout_seconds": payload.timeout_seconds,
    }
    if entry_point == "http_endpoint":
        snapshot.update(
            {
                "url": _check_url(payload.target),
                "method": payload.method.upper(),
                "headers": dict(payload.headers),
                "body_template": payload.body_template or _DEFAULT_BODY_TEMPLATE,
                "answer_path": payload.answer_path,
                "context_path": payload.context_path,
                "allow_private_targets": payload.allow_private_targets,
                "max_concurrency": payload.max_concurrency,
                "min_delay_ms": payload.min_delay_ms,
                "max_retries": payload.max_retries,
                "response_format": payload.response_format,
                "stream_content_path": payload.stream_content_path,
            }
        )
    elif entry_point == "prompt_app":
        if payload.provider_id is None:
            raise RunServiceError(
                "Pick a model provider in Settings > Providers, then start the test again."
            )
        snapshot.update(
            {
                "system_prompt": payload.system_prompt or payload.target,
                "provider_id": str(payload.provider_id),
                "model": payload.model,
                "temperature": payload.temperature,
            }
        )
    elif entry_point == "upload_outputs":
        if not payload.body_template or not payload.body_template.strip():
            raise RunServiceError(
                "Upload-output runs need the CSV or JSON file. Paste it in the Upload outputs "
                "panel on the New Test page, then start the test again."
            )
        snapshot.update(
            {
                "csv": payload.body_template,
                "dataset_version_id": str(dataset_version_id),
                "column_overrides": (
                    dict(payload.column_overrides) if payload.column_overrides else None
                ),
            }
        )
    return snapshot


def _check_test_types(test_types: Sequence[str]) -> Sequence[str]:
    if not test_types:
        raise RunServiceError("Pick at least one test type — Quality, Safety or Operations.")
    return test_types


def _safety_selection(requested: Sequence[str] | None) -> SafetySelection:
    """Validate the run's safety sets, turning a bad choice into a 422."""
    try:
        return resolve_safety_sets(requested)
    except SafetySetError as exc:
        raise RunServiceError(exc.message, status=422, code="invalid_safety_sets") from exc


def resolve_judge_profile(session: Session, user: User, requested: uuid.UUID | None) -> str | None:
    """The judge for this run: the requested profile, else the selected one.

    Selecting a profile in Settings > Judge is what makes it the default, so a
    run judges its answers without the New Test page having to send an id.
    """
    if requested is not None:
        profile = get_judge_profile(session, requested, owner_id=user.id)
        if profile is None:
            raise RunServiceError(
                "That judge profile was not found. Pick one in Settings > Judge.",
                status=404,
                code="not_found",
            )
        return str(profile.id)
    selected = selected_judge_profile(session, user.id)
    return str(selected.id) if selected is not None else None


def create_run_from_request(
    session: Session,
    user: User,
    payload: RunCreateRequest,
    enqueue: Enqueue,
) -> Run:
    """Validate, snapshot, persist and queue one run."""
    test_types = list(_check_test_types(payload.test_types))
    entry = payload.entry_point
    dataset, version = _approved_version(
        session,
        user,
        dataset_id=payload.dataset_id,
        dataset_version_id=payload.dataset_version_id,
    )
    snapshot = build_snapshot(payload, dataset_version_id=version.id, entry_point=entry)
    snapshot["test_types"] = test_types
    if "safety" in test_types:
        snapshot["safety_sets"] = list(_safety_selection(payload.safety_sets).ids)
    judge_id = resolve_judge_profile(session, user, payload.judge_profile_id)
    if judge_id is not None:
        snapshot["judge_profile_id"] = judge_id
    profile = resolve_criteria_profile(payload.criteria_profile, snapshot)
    run = create_run(
        session,
        owner_id=user.id,
        name=payload.name or _default_name(entry),
        settings_snapshot=snapshot,
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        criteria_profile=profile,
    )
    session.commit()
    enqueue(run.id)
    return run


def cancel_run(session: Session, run: Run) -> Run:
    """Cancel: queued runs stop now, running runs stop at the next case boundary."""
    if run.state == RunState.QUEUED.value:
        run.state = RunState.CANCELLED.value
        run.is_partial = True
        run.verdict_reason = "This run was cancelled before it started."
        run.completed_at = utcnow()
        session.commit()
        return run
    if run.state == RunState.RUNNING.value:
        run.state = RunState.CANCELLING.value
        session.commit()
        return run
    if run.state == RunState.CANCELLING.value:
        return run
    raise RunServiceError(
        f"This run is already {run.state}, so there is nothing to cancel.",
        status=409,
        code="conflict",
    )


def _default_name(entry_point: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    label = {
        "http_endpoint": "HTTP endpoint",
        "prompt_app": "Prompt app",
        "upload_outputs": "Uploaded outputs",
    }.get(entry_point, entry_point)
    return f"{label} test — {stamp}"


def _provider_for(session: Session, user: User, provider_id: uuid.UUID | None) -> Provider:
    if provider_id is not None:
        provider = session.get(Provider, provider_id)
        if provider is None:
            raise RunServiceError(
                "That model provider was not found. Pick one in Settings > Providers.",
                status=404,
                code="not_found",
            )
        return provider
    provider = session.scalar(
        select(Provider).where(Provider.is_active.is_(True)).order_by(Provider.created_at)
    )
    if provider is None:
        raise RunServiceError(
            "Generating test cases needs a model provider. Add one in Settings > "
            "Providers, or send a CSV dataset with the quick test."
        )
    return provider


def _csv_from_cases(cases: list[dict[str, Any]]) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["question", "answer", "context", "category"])
    for case in cases:
        writer.writerow(
            [
                case.get("question", ""),
                case.get("answer", ""),
                case.get("context") or "",
                case.get("category") or "",
            ]
        )
    return buffer.getvalue()


def create_quick_test(
    session: Session,
    user: User,
    payload: QuickTestRequest,
    enqueue: Enqueue,
    chat: ChatFn,
) -> tuple[Run, DatasetVersion, bool]:
    """Create whatever the quick test needs and start it (spec section 9).

    Returns the run, the approved dataset version and whether the cases were
    generated by the model (rather than uploaded or picked).
    """
    generated = False
    if payload.csv and payload.csv.strip():
        dataset = _dataset_from_csv(
            session, user, payload.name or _default_name(payload.entry_point), payload.csv.encode()
        )
        version = _approve_first_version(session, dataset, user)
    elif payload.dataset_id is not None:
        dataset, version = _approved_version(
            session, user, dataset_id=payload.dataset_id, dataset_version_id=None
        )
    elif payload.entry_point == "upload_outputs":
        if not payload.csv or not payload.csv.strip():
            raise RunServiceError(
                "Upload-output quick tests need the CSV or JSON file. "
                "Send `csv` with the quick test."
            )
        dataset = _dataset_from_csv(
            session, user, payload.name or _default_name(payload.entry_point), payload.csv.encode()
        )
        version = _approve_first_version(session, dataset, user)
    else:
        provider = _provider_for(session, user, payload.provider_id)
        try:
            cases = generate_test_cases(provider, count=payload.generate, chat=chat)
        except GenerationError as exc:
            raise RunServiceError(
                f"Could not generate test cases: {exc.message} "
                "Upload a CSV dataset instead, or fix the provider.",
                status=502,
                code="generation_failed",
            ) from exc
        dataset = _dataset_from_csv(
            session,
            user,
            payload.name or _default_name(payload.entry_point),
            _csv_from_cases(cases).encode(),
        )
        version = _approve_first_version(session, dataset, user)
        version.generated = True
        generated = True
        session.flush()

    request = RunCreateRequest(
        name=payload.name or _default_name(payload.entry_point),
        entry_point=payload.entry_point,
        target=payload.target,
        test_types=payload.tests,
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        provider_id=payload.provider_id,
        model=payload.model,
        method=payload.method,
        body_template=(
            payload.csv if payload.entry_point == "upload_outputs" else payload.body_template
        ),
        headers=payload.headers,
        answer_path=payload.answer_path,
        context_path=payload.context_path,
        timeout_seconds=payload.timeout_seconds,
        allow_private_targets=payload.allow_private_targets,
        max_concurrency=payload.max_concurrency,
        min_delay_ms=payload.min_delay_ms,
        max_retries=payload.max_retries,
        response_format=payload.response_format,
        stream_content_path=payload.stream_content_path,
        safety_sets=payload.safety_sets,
    )
    run = create_run_from_request(session, user, request, enqueue)
    return run, version, generated


def _dataset_from_csv(session: Session, user: User, name: str, raw: bytes) -> Dataset:
    """Store an uploaded CSV as a dataset; a duplicate name gets a suffix."""
    candidate = name
    for attempt in range(1, 6):
        try:
            return create_dataset(
                session,
                owner_id=user.id,
                name=candidate,
                source_filename="quick-test.csv",
                raw_content=raw,
            )
        except DatasetError as exc:
            if exc.code != "duplicate_name":
                raise RunServiceError(exc.message, status=400) from exc
            candidate = f"{name} ({attempt})"
    raise RunServiceError("Could not name the quick-test dataset. Pick a different name.")


def _approve_first_version(session: Session, dataset: Dataset, user: User) -> DatasetVersion:
    try:
        return approve_dataset_version(session, dataset, 1, user.id)
    except DatasetError as exc:
        raise RunServiceError(exc.message, status=400) from exc
