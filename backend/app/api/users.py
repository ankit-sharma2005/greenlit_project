"""User administration: admin-only listing and role changes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_admin
from app.models import ROLE_ADMIN, User
from app.schemas.auth import UserRead
from app.schemas.users import RoleUpdateRequest, UserListResponse
from app.services import audit

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=UserListResponse)
def list_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserListResponse:
    """List accounts (admin only)."""
    total = db.scalar(select(func.count()).select_from(User)) or 0
    users = db.scalars(
        select(User).order_by(User.created_at, User.email).limit(limit).offset(offset)
    ).all()
    return UserListResponse(
        items=[UserRead.model_validate(user) for user in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{user_id}/role", response_model=UserRead)
def change_role(
    user_id: uuid.UUID,
    payload: RoleUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserRead:
    """Change a user's role (admin only). The last admin cannot be demoted."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if target.role == ROLE_ADMIN and payload.role != ROLE_ADMIN:
        admin_count = db.scalar(
            select(func.count()).select_from(User).where(User.role == ROLE_ADMIN)
        )
        if (admin_count or 0) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last admin cannot be demoted. Promote another admin first.",
            )

    previous = target.role
    target.role = payload.role
    audit.record(
        db,
        "user.role_changed",
        actor_id=admin.id,
        target_type="user",
        target_id=str(target.id),
        metadata={"from": previous, "to": payload.role},
        request=request,
    )
    db.commit()
    db.refresh(target)
    return UserRead.model_validate(target)
