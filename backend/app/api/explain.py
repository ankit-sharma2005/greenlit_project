"""Analyst endpoints: preview, explain, read (PART 2).

Ownership is checked before anything is built, so another account's run never reaches the
analyst input. The only database write is one `run_explanations` row.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Provider, Run, RunExplanation, User
from app.schemas.analyst import (
    ExplanationPreview,
    ExplanationRead,
    ExplanationRequest,
)
from app.services import analyst
from app.services.generation import ChatFn, get_chat_fn
from app.services.run_repository import get_metric_results, list_run_items

router = APIRouter(prefix="/api/v1", tags=["analyst"])

_STATUS_BY_CODE = {
    "rate_limited": 429,
    "auth_error": 502,
    "connection_error": 502,
    "timeout_error": 504,
}


def _owned_run(db: Session, run_id: uuid.UUID, user: User) -> Run:
    """404 for a run that is missing or belongs to someone else."""
    run = db.get(Run, run_id)
    if run is None or run.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


def _analyst_choice(db: Session, user: User) -> tuple[Provider, str]:
    """The saved analyst provider and model, validated like every other role."""
    raw = (user.preferences or {}).get("analyst")
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=422,
            detail="Choose an analyst provider and model in Settings first.",
        )
    try:
        provider_id = uuid.UUID(str(raw["provider_id"]))
        model = str(raw["model"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Choose an analyst provider and model in Settings first.",
        ) from None
    provider = db.get(Provider, provider_id)
    if provider is None or not provider.is_active:
        raise HTTPException(status_code=422, detail="That analyst provider is not available.")
    return provider, model


def _preview(
    db: Session, run: Run, provider: Provider, model: str
) -> tuple[ExplanationPreview, str]:
    text = analyst.build_input(run, get_metric_results(db, run.id), list_run_items(db, run.id))
    preview = ExplanationPreview(
        input=text,
        input_hash=analyst.input_hash(text),
        provider_id=provider.id,
        provider_name=provider.name,
        model=model,
        prompt_version=analyst.PROMPT_VERSION,
        provider_is_local=analyst.provider_is_local(provider),
    )
    return preview, text


def _stored(row: RunExplanation | None, provider_name: str | None = None) -> ExplanationRead:
    if row is None:
        return ExplanationRead(status="none", message="This run has not been explained yet.")
    if row.status == "ok":
        return ExplanationRead(
            status="ok",
            text=row.text,
            model=row.model,
            provider_name=provider_name,
            prompt_version=row.prompt_version,
            created_at=row.created_at,
            input_hash=row.input_hash,
        )
    return ExplanationRead(
        status="rejected" if row.status == "rejected" else "error",
        message=(
            "The model's answer was not stored because it broke the safety rules "
            "(a link, HTML, a secret or the canary). Try again, or read the run yourself."
            if row.status == "rejected"
            else "The analyst could not answer. Nothing was changed."
        ),
        model=row.model,
        provider_name=provider_name,
        prompt_version=row.prompt_version,
        created_at=row.created_at,
        input_hash=row.input_hash,
    )


@router.post("/runs/{run_id}/explain/preview", response_model=ExplanationPreview)
def preview_explanation(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExplanationPreview:
    """Show exactly what would be sent, before anything is sent."""
    run = _owned_run(db, run_id, user)
    provider, model = _analyst_choice(db, user)
    preview, _ = _preview(db, run, provider, model)
    return preview


@router.post("/runs/{run_id}/explain", response_model=ExplanationRead)
def explain_run(
    run_id: uuid.UUID,
    payload: ExplanationRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    chat: ChatFn = Depends(get_chat_fn),
) -> ExplanationRead:
    """Explain a finished run once per distinct input; a cache hit costs no call."""
    body = payload or ExplanationRequest()
    run = _owned_run(db, run_id, user)
    provider, model = _analyst_choice(db, user)
    preview, text = _preview(db, run, provider, model)

    cached = (
        db.execute(
            select(RunExplanation).where(
                RunExplanation.run_id == run.id,
                RunExplanation.input_hash == preview.input_hash,
            )
        )
        .scalars()
        .first()
    )
    if cached is not None:
        return _stored(cached, provider.name)

    if not preview.provider_is_local and not body.confirm_remote:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{provider.name}' is a remote provider, so this run's summary would leave "
                "your machine. Confirm to send it."
            ),
        )

    try:
        outcome = analyst.explain(text, provider=provider, model=model, chat=chat)
    except analyst.AnalystError as exc:
        raise HTTPException(
            status_code=_STATUS_BY_CODE.get(exc.code, 502),
            detail=exc.message,
        ) from exc

    row = RunExplanation(
        run_id=run.id,
        input_hash=preview.input_hash,
        provider_id=provider.id,
        model=model,
        prompt_version=analyst.PROMPT_VERSION,
        status=outcome.status,
        text=outcome.text,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _stored(row, provider.name)


@router.get("/runs/{run_id}/explanation", response_model=ExplanationRead)
def get_explanation(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ExplanationRead:
    """The latest stored explanation, or a neutral message. Never calls a model."""
    run = _owned_run(db, run_id, user)
    row = (
        db.execute(
            select(RunExplanation)
            .where(RunExplanation.run_id == run.id)
            .order_by(RunExplanation.created_at.desc())
        )
        .scalars()
        .first()
    )
    provider_name: str | None = None
    if row is not None and row.provider_id is not None:
        provider = db.get(Provider, row.provider_id)
        provider_name = provider.name if provider is not None else None
    return _stored(row, provider_name)
