"""Saved target endpoints (M13): the Settings → Connectors shelf.

Personal like datasets and judge profiles: the owner comes from the session and a
missing or foreign target answers 404, so its existence never leaks. The audit
trail records the change and which format was saved, but not the URL — a query
string can carry a token, and the trail is not the place for one.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import SavedTarget, User
from app.schemas.saved_targets import (
    SavedTargetCreate,
    SavedTargetListResponse,
    SavedTargetRead,
    SavedTargetUpdate,
)
from app.services.audit import record
from app.services.saved_targets import (
    SavedTargetError,
    create_saved_target,
    delete_saved_target,
    get_saved_target,
    list_saved_targets,
    update_saved_target,
)

router = APIRouter(prefix="/api/v1/saved-targets", tags=["connectors"])


def _error(exc: SavedTargetError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _metadata(target: SavedTarget) -> dict[str, object]:
    """What a change touched, without the URL or any header value."""
    return {
        "connector_type": target.connector_type,
        "method": target.method,
        "response_format": target.response_format,
        "header_names": target.header_names,
        "allow_private_targets": target.allow_private_targets,
    }


@router.get("", response_model=SavedTargetListResponse)
def list_targets(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SavedTargetListResponse:
    """Every target the signed-in user saved, oldest first."""
    targets = list_saved_targets(db, user.id)
    return SavedTargetListResponse(
        items=[SavedTargetRead.model_validate(target) for target in targets],
        total=len(targets),
    )


@router.post("", response_model=SavedTargetRead, status_code=201)
def create_target(
    payload: SavedTargetCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SavedTargetRead:
    """Save a target's location and request/response format."""
    try:
        target = create_saved_target(db, owner_id=user.id, **payload.model_dump())
    except SavedTargetError as exc:
        db.rollback()
        raise _error(exc) from exc
    record(
        db,
        "saved_target.create",
        actor_id=user.id,
        target_type="saved_target",
        target_id=str(target.id),
        metadata=_metadata(target),
        request=request,
    )
    db.commit()
    db.refresh(target)
    return SavedTargetRead.model_validate(target)


@router.patch("/{target_id}", response_model=SavedTargetRead)
def update_target(
    target_id: uuid.UUID,
    payload: SavedTargetUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SavedTargetRead:
    """Change only the fields that were sent; an explicit null clears one."""
    target = get_saved_target(db, target_id, owner_id=user.id)
    if target is None:
        raise HTTPException(status_code=404, detail="Saved target not found.")
    try:
        target = update_saved_target(db, target, **payload.model_dump(exclude_unset=True))
    except SavedTargetError as exc:
        db.rollback()
        raise _error(exc) from exc
    record(
        db,
        "saved_target.update",
        actor_id=user.id,
        target_type="saved_target",
        target_id=str(target.id),
        metadata={**_metadata(target), "changed": sorted(payload.model_dump(exclude_unset=True))},
        request=request,
    )
    db.commit()
    db.refresh(target)
    return SavedTargetRead.model_validate(target)


@router.delete("/{target_id}", status_code=204, response_model=None)
def delete_target(
    target_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Remove one of the signed-in user's saved targets."""
    target = get_saved_target(db, target_id, owner_id=user.id)
    if target is None:
        raise HTTPException(status_code=404, detail="Saved target not found.")
    delete_saved_target(db, target)
    record(
        db,
        "saved_target.delete",
        actor_id=user.id,
        target_type="saved_target",
        target_id=str(target_id),
        metadata={},
        request=request,
    )
    db.commit()
