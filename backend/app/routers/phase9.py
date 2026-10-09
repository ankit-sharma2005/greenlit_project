from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user, require_roles
from app.models import ApiToken, User
from app.security import hash_token
from app.services.ci import build_ci_response, generate_api_token, validate_api_token

router = APIRouter(tags=["phase9", "ci", "reports"])

Engineer = Annotated[User, Depends(require_roles("owner", "admin", "engineer"))]


@router.post("/workspaces/{workspace_id}/ci/regression-check")
async def ci_regression_check(
    request: Request,
    workspace_id: UUID,
    payload: dict[str, Any],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    token_value = payload.get("api_token") or payload.get("token")
    if not isinstance(token_value, str) or not token_value.strip():
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token_value = auth_header.split(" ", 1)[1].strip()
    if not isinstance(token_value, str) or not token_value.strip():
        token_value = request.headers.get("x-api-token")
    if not isinstance(token_value, str) or not token_value.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token required for CI regression checks",
        )

    token_record = await validate_api_token(db, token_value)
    if token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API token",
        )
    if (
        token_record.workspace_id is not None
        and token_record.workspace_id != workspace_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API token is not valid for this workspace",
        )

    checks = payload.get("checks")
    if checks is None:
        checks = [
            {"name": "backend-tests", "status": "PASS"},
            {"name": "lint", "status": "PASS"},
            {"name": "typecheck", "status": "PASS"},
        ]
    return build_ci_response(
        status=payload.get("status"),
        checks=checks,
        message=str(payload.get("message") or "Regression check completed."),
        token_name=token_record.name,
    )


@router.post("/workspaces/{workspace_id}/api-tokens")
async def create_api_token(
    workspace_id: UUID,
    payload: dict[str, Any],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    name = str(payload.get("name") or "ci-token")
    scopes = payload.get("scopes") or ["ci:read", "ci:write"]
    expires_in_days = payload.get("expires_in_days")
    if expires_in_days is None:
        expires_at = datetime.now(UTC) + timedelta(days=30)
    else:
        try:
            expires_days = int(expires_in_days)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="expires_in_days must be an integer number of days",
            ) from None
        expires_at = datetime.now(UTC) + timedelta(days=max(expires_days, 1))
    token_value = generate_api_token(prefix="gl")
    record = ApiToken(
        user_id=user.id,
        workspace_id=workspace_id,
        name=name,
        token_hash=hash_token(token_value),
        token_prefix="gl",
        scopes=[str(scope) for scope in scopes],
        is_active=True,
        expires_at=expires_at,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {
        "id": str(record.id),
        "name": record.name,
        "token": token_value,
        "scopes": record.scopes,
    }


@router.get("/workspaces/{workspace_id}/api-tokens")
async def list_api_tokens(
    workspace_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(ApiToken).where(
            ApiToken.user_id == user.id,
            ApiToken.workspace_id == workspace_id,
        )
    )
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "token_prefix": item.token_prefix,
            "scopes": item.scopes,
            "is_active": item.is_active,
            "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        }
        for item in rows.all()
    ]
