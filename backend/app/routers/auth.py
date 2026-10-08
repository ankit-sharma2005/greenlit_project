import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.mailer import password_reset_delivery_configured, send_password_reset
from app.models import (
    AuditLog,
    PasswordResetToken,
    RefreshToken,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.schemas import (
    PasswordResetConfirm,
    PasswordResetRequest,
    UserCreate,
    UserLogin,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path="/",
    )


async def _write_audit(
    db: AsyncSession,
    user_id: UUID | None,
    workspace_id: UUID | None,
    action: str,
    details: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            workspace_id=workspace_id,
            action=action,
            details=details or {},
        )
    )
    await db.commit()


async def _create_workspace_for_user(
    db: AsyncSession, user: User, workspace_name: str
) -> Workspace:
    slug = f"{user.email.split('@')[0]}-workspace".lower().replace(".", "-")
    workspace = Workspace(name=workspace_name, slug=slug, owner_id=user.id)
    db.add(workspace)
    await db.flush()
    db.add(
        WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, role="owner")
    )
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace.id,
            action="workspace_created",
            details={},
        )
    )
    await db.flush()
    return workspace


@router.post("/signup")
async def signup(
    payload: UserCreate,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    user = User(
        email=payload.email, password_hash=hash_password(payload.password), role="owner"
    )
    db.add(user)
    await db.flush()

    workspace = await _create_workspace_for_user(db, user, payload.workspace_name)
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    db.add(
        RefreshToken(
            user_id=user.id,
            workspace_id=workspace.id,
            token_hash=hash_token(refresh_token),
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await _write_audit(db, user.id, workspace.id, "signup")
    _set_refresh_cookie(response, refresh_token)
    return {
        "access_token": access_token,
        "user": {"id": str(user.id), "email": user.email, "role": user.role},
        "workspace": {"id": str(workspace.id), "name": workspace.name},
    }


@router.post("/login")
async def login(
    payload: UserLogin,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    membership = await db.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user.id)
        .limit(1)
    )
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    db.add(
        RefreshToken(
            user_id=user.id,
            workspace_id=membership.workspace_id if membership else None,
            token_hash=hash_token(refresh_token),
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
    await _write_audit(
        db, user.id, membership.workspace_id if membership else None, "login"
    )
    _set_refresh_cookie(response, refresh_token)
    return {
        "access_token": access_token,
        "user": {"id": str(user.id), "email": user.email, "role": user.role},
    }


@router.post("/refresh")
async def refresh(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> dict[str, str]:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token required"
        )

    try:
        decoded = decode_token(refresh_token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from exc

    if decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    token_record = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(refresh_token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(UTC),
        )
    )
    if token_record is None or str(token_record.user_id) != str(decoded.get("sub")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not recognized",
        )

    new_access_token = create_access_token(str(decoded["sub"]))
    new_refresh_token = create_refresh_token(str(decoded["sub"]))
    token_record.token_hash = hash_token(new_refresh_token)
    token_record.expires_at = datetime.now(UTC) + timedelta(
        days=settings.refresh_token_ttl_days
    )
    db.add(
        AuditLog(
            user_id=token_record.user_id,
            workspace_id=token_record.workspace_id,
            action="refresh_rotation",
            details={},
        )
    )
    await db.commit()
    _set_refresh_cookie(response, new_refresh_token)
    return {"access_token": new_access_token}


@router.post("/logout")
async def logout(
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> dict[str, bool]:
    if refresh_token:
        token_record = await db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_token(refresh_token),
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        if token_record is not None:
            token_record.revoked_at = datetime.now(UTC)
    response.delete_cookie("refresh_token", path="/", samesite="lax")
    await _write_audit(db, user.id, None, "logout")
    return {"ok": True}


@router.post("/password-reset/request")
async def request_password_reset(
    payload: PasswordResetRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str | bool]:
    if not password_reset_delivery_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password reset delivery is not configured",
        )

    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is not None and user.is_active:
        now = datetime.now(UTC)
        existing_tokens = await db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )
        for existing_token in existing_tokens:
            existing_token.used_at = now

        token = secrets.token_urlsafe(32)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=now + timedelta(hours=1),
            )
        )
        await db.commit()
        await asyncio.to_thread(send_password_reset, user.email, token)

    return {
        "ok": True,
        "message": "If the account exists, reset instructions have been sent.",
    }


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    payload: PasswordResetConfirm,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    now = datetime.now(UTC)
    reset_token = await db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(payload.token),
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    if reset_token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token",
        )

    user = await db.get(User, reset_token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token",
        )

    user.password_hash = hash_password(payload.password)
    reset_token.used_at = now
    refresh_tokens = await db.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    for refresh_token in refresh_tokens:
        refresh_token.revoked_at = now

    db.add(AuditLog(user_id=user.id, action="password_reset", details={}))
    await db.commit()
    return {"ok": True}


@router.get("/me")
async def me(user: Annotated[User, Depends(get_current_user)]) -> dict[str, str | bool]:
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
    }
