"""Draft dataset endpoints: generate, review item by item, publish approved items."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Dataset, DatasetDraft, DraftItem, Provider, User
from app.schemas.datasets import DatasetVersionRead
from app.schemas.drafts import (
    DraftCreateRequest,
    DraftItemUpdate,
    DraftListResponse,
    DraftRead,
)
from app.services import audit
from app.services.drafts import DraftError, generate_draft, publish_draft
from app.services.generation import ChatFn, GenerationError, get_chat_fn
from app.services.llm_gateway import GatewayError

router = APIRouter(prefix="/api/v1/dataset-drafts", tags=["dataset-drafts"])

_STATUS_BY_CODE = {
    "rate_limited": 429,
    "invalid_response": 422,
    "nothing_approved": 400,
    "duplicate_name": 409,
}


def _owned_draft(db: Session, draft_id: uuid.UUID, user: User) -> DatasetDraft:
    """404 for a draft that is missing or belongs to someone else."""
    draft = db.get(DatasetDraft, draft_id)
    if draft is None or draft.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Draft not found.")
    return draft


def _stored_choice(user: User, role: str) -> tuple[uuid.UUID | None, str | None]:
    """A saved role default, tolerating a hand-edited or half-written document."""
    raw = (user.preferences or {}).get(role)
    if not isinstance(raw, dict):
        return None, None
    try:
        return uuid.UUID(str(raw["provider_id"])), str(raw["model"])
    except (KeyError, ValueError):
        return None, None


@router.post("", response_model=DraftRead, status_code=201)
def create_draft(
    payload: DraftCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    chat: ChatFn = Depends(get_chat_fn),
) -> DraftRead:
    """Generate a draft. Nothing here is usable in a run until it is approved and published."""
    stored_provider, stored_model = _stored_choice(user, "generator")
    provider_id = payload.provider_id or stored_provider
    if provider_id is None:
        raise HTTPException(
            status_code=422,
            detail="Choose a generator provider, or save a default in Settings first.",
        )
    provider = db.get(Provider, provider_id)
    if provider is None or not provider.is_active:
        raise HTTPException(
            status_code=422,
            detail="That generator provider is not available.",
        )
    model = (payload.model or stored_model or provider.model_name).strip()
    judge_provider, judge_model = _stored_choice(user, "judge")
    same_as_judge = (
        judge_provider is not None
        and judge_provider == provider.id
        and (judge_model or "").casefold() == model.casefold()
    )

    try:
        draft = generate_draft(
            db,
            user,
            provider,
            name=payload.name,
            app_description=payload.app_description,
            count=payload.count,
            kinds=list(payload.kinds),
            documents=payload.documents,
            same_as_judge=same_as_judge,
            model=model,
            chat=chat,
        )
        audit.record(
            db,
            "dataset_draft.created",
            actor_id=user.id,
            target_type="dataset_draft",
            target_id=str(draft.id),
            metadata={
                "count": len(draft.items),
                "model": draft.generated_by_model,
                "prompt_version": draft.prompt_version,
            },
        )
        db.commit()
    except (GenerationError, GatewayError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=_STATUS_BY_CODE.get(exc.code, 502), detail=exc.message
        ) from exc
    db.refresh(draft)
    return DraftRead.model_validate(draft)


@router.get("", response_model=DraftListResponse)
def list_drafts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DraftListResponse:
    """The signed-in user's drafts, newest first."""
    owned = DatasetDraft.owner_id == user.id
    total = db.scalar(select(func.count()).select_from(DatasetDraft).where(owned)) or 0
    drafts = db.scalars(
        select(DatasetDraft).where(owned).order_by(DatasetDraft.created_at.desc()).limit(20)
    ).all()
    return DraftListResponse(
        items=[DraftRead.model_validate(draft) for draft in drafts],
        total=total,
    )


@router.get("/{draft_id}", response_model=DraftRead)
def get_draft(
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DraftRead:
    """One draft with its items."""
    return DraftRead.model_validate(_owned_draft(db, draft_id, user))


@router.patch("/{draft_id}/items/{item_id}", response_model=DraftRead)
def review_item(
    draft_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: DraftItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DraftRead:
    """Approve, reject or edit one item. Every change is recorded on the item."""
    draft = _owned_draft(db, draft_id, user)
    item = db.get(DraftItem, item_id)
    if item is None or item.draft_id != draft.id:
        raise HTTPException(status_code=404, detail="Draft item not found.")

    changed: list[str] = []
    if payload.question is not None and payload.question.strip() != item.question:
        item.question = payload.question.strip()
        item.edited = True
        changed.append("question")
    if (
        payload.expected_answer is not None
        and payload.expected_answer.strip() != item.expected_answer
    ):
        item.expected_answer = payload.expected_answer.strip()
        item.edited = True
        changed.append("expected_answer")
    if payload.source_passage is not None:
        passage = payload.source_passage.strip() or None
        if passage != item.source_passage:
            item.source_passage = passage
            item.edited = True
            changed.append("source_passage")
    if payload.status is not None and payload.status != item.status:
        item.status = payload.status
        changed.append("status")

    if changed:
        item.reviewer_id = user.id
        item.reviewed_at = datetime.now(UTC)
        audit.record(
            db,
            "dataset_draft.item_reviewed",
            actor_id=user.id,
            target_type="dataset_draft",
            target_id=str(draft.id),
            metadata={"changed": changed, "status": item.status},
        )
    db.commit()
    db.refresh(draft)
    return DraftRead.model_validate(draft)


@router.post("/{draft_id}/items/approve-all", response_model=DraftRead)
def approve_all_items(
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DraftRead:
    """Approve every item still pending; rejected items stay rejected."""
    draft = _owned_draft(db, draft_id, user)
    now = datetime.now(UTC)
    approved = 0
    for item in draft.items:
        if item.status == "pending":
            item.status = "approved"
            item.reviewer_id = user.id
            item.reviewed_at = now
            approved += 1
    audit.record(
        db,
        "dataset_draft.items_approved",
        actor_id=user.id,
        target_type="dataset_draft",
        target_id=str(draft.id),
        metadata={"approved": approved},
    )
    db.commit()
    db.refresh(draft)
    return DraftRead.model_validate(draft)


@router.post("/{draft_id}/publish", response_model=DatasetVersionRead, status_code=201)
def publish(
    draft_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetVersionRead:
    """Publish approved items as a new, approved, versioned dataset."""
    draft = _owned_draft(db, draft_id, user)
    if draft.published_version_id is not None:
        raise HTTPException(
            status_code=409,
            detail="This draft has already been published. Generate a new draft for new items.",
        )
    if (
        db.scalar(select(Dataset.id).where(Dataset.owner_id == user.id, Dataset.name == draft.name))
        is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="A dataset with that name already exists. Rename the draft before publishing.",
        )
    try:
        version = publish_draft(db, draft, user)
    except DraftError as exc:
        db.rollback()
        raise HTTPException(
            status_code=_STATUS_BY_CODE.get(exc.code, 400), detail=exc.message
        ) from exc
    audit.record(
        db,
        "dataset_draft.published",
        actor_id=user.id,
        target_type="dataset_draft",
        target_id=str(draft.id),
        metadata={
            "dataset_id": str(draft.published_dataset_id),
            "version_no": version.version_no,
            "items": version.row_count,
            "model": draft.generated_by_model,
            "prompt_version": draft.prompt_version,
        },
    )
    db.commit()
    db.refresh(version)
    return DatasetVersionRead.model_validate(version)
