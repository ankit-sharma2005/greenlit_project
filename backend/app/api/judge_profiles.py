"""Judge profile endpoints: save, list, select and delete (M7).

Profiles are personal (owner-scoped) like datasets: a missing or foreign profile
answers 404 so its existence never leaks. The self-grading warning travels with
every response, so the UI never has to recompute it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import JudgeProfile, Provider, User
from app.schemas.judge_profiles import (
    JudgeProfileCreate,
    JudgeProfileListResponse,
    JudgeProfileRead,
)
from app.services.audit import record
from app.services.judge_profiles import (
    JudgeProfileError,
    create_judge_profile,
    delete_judge_profile,
    effective_model,
    get_judge_profile,
    judge_warnings,
    list_judge_profiles,
    select_judge_profile,
    selected_judge_profile,
)

router = APIRouter(prefix="/api/v1/judge-profiles", tags=["judge"])


def _error(exc: JudgeProfileError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _read(db: Session, profile: JudgeProfile) -> JudgeProfileRead:
    """A profile plus its provider name and current self-grading warnings."""
    provider = db.get(Provider, profile.provider_id) if profile.provider_id else None
    model = effective_model(profile, provider)
    return JudgeProfileRead(
        id=profile.id,
        name=profile.name,
        provider_id=profile.provider_id,
        provider_name=provider.name if provider is not None else None,
        model=model,
        rubric_version=profile.rubric_version,
        temperature=profile.temperature,
        max_tokens=profile.max_tokens,
        max_cases=profile.max_cases,
        is_selected=profile.is_selected,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        warnings=judge_warnings(db, provider_id=profile.provider_id, model=model),
    )


@router.post("", response_model=JudgeProfileRead, status_code=201)
def create_profile(
    payload: JudgeProfileCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JudgeProfileRead:
    """Save a judge profile; the first one is selected automatically."""
    try:
        profile = create_judge_profile(
            db,
            owner_id=user.id,
            name=payload.name,
            provider_id=payload.provider_id,
            model=payload.model,
            max_tokens=payload.max_tokens,
            max_cases=payload.max_cases,
        )
    except JudgeProfileError as exc:
        db.rollback()
        raise _error(exc) from exc
    response = _read(db, profile)
    record(
        db,
        "judge_profile.create",
        actor_id=user.id,
        target_type="judge_profile",
        target_id=str(profile.id),
        metadata={
            "provider_id": str(profile.provider_id) if profile.provider_id else None,
            "model": response.model,
            "rubric_version": profile.rubric_version,
            "max_cases": profile.max_cases,
            "self_grading_warning": bool(response.warnings),
        },
        request=request,
    )
    db.commit()
    db.refresh(profile)
    return _read(db, profile)


@router.get("", response_model=JudgeProfileListResponse)
def list_profiles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JudgeProfileListResponse:
    """Every profile the signed-in user saved, oldest first."""
    profiles = list_judge_profiles(db, user.id)
    selected = selected_judge_profile(db, user.id)
    return JudgeProfileListResponse(
        items=[_read(db, profile) for profile in profiles],
        total=len(profiles),
        selected_id=selected.id if selected is not None else None,
    )


@router.post("/{profile_id}/select", response_model=JudgeProfileRead)
def select_profile(
    profile_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JudgeProfileRead:
    """Make this profile the default judge for new runs."""
    profile = get_judge_profile(db, profile_id, owner_id=user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Judge profile not found.")
    select_judge_profile(db, profile)
    response = _read(db, profile)
    record(
        db,
        "judge_profile.select",
        actor_id=user.id,
        target_type="judge_profile",
        target_id=str(profile.id),
        metadata={"model": response.model, "rubric_version": profile.rubric_version},
        request=request,
    )
    db.commit()
    db.refresh(profile)
    return _read(db, profile)


@router.delete("/{profile_id}", status_code=204, response_model=None)
def delete_profile(
    profile_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete one of the signed-in user's profiles."""
    profile = get_judge_profile(db, profile_id, owner_id=user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Judge profile not found.")
    delete_judge_profile(db, profile)
    record(
        db,
        "judge_profile.delete",
        actor_id=user.id,
        target_type="judge_profile",
        target_id=str(profile_id),
        metadata={},
        request=request,
    )
    db.commit()
