from __future__ import annotations

import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiToken
from app.security import hash_token

StatusValue = Literal["PASS", "WARN", "BLOCK"]


def generate_api_token(prefix: str = "gl", *, token_length: int = 24) -> str:
    return f"{prefix}_{secrets.token_urlsafe(token_length)}"


def normalize_ci_status(value: Any) -> StatusValue:
    if value is None:
        return "PASS"
    key = str(value).strip().upper()
    if key in {"WARN", "WARNING"}:
        return "WARN"
    if key in {"BLOCK", "FAIL", "FAILED", "ERROR"}:
        return "BLOCK"
    if key in {"PASS", "OK", "SUCCESS", "SUCCESSFUL"}:
        return "PASS"
    return "PASS"


def summarize_ci_status(checks: Sequence[Mapping[str, Any]] | None) -> StatusValue:
    if not checks:
        return "PASS"
    if any(
        normalize_ci_status(item.get("status")) == "BLOCK"
        or normalize_ci_status(item.get("result")) == "BLOCK"
        or item.get("ok") is False
        for item in checks
    ):
        return "BLOCK"
    if any(
        normalize_ci_status(item.get("status")) == "WARN"
        or normalize_ci_status(item.get("result")) == "WARN"
        for item in checks
    ):
        return "WARN"
    return "PASS"


async def validate_api_token(
    db: AsyncSession, token_value: str
) -> ApiToken | None:
    token_hash = hash_token(token_value)
    now = datetime.now(UTC)
    record = await db.scalar(
        select(ApiToken).where(
            ApiToken.token_hash == token_hash,
            ApiToken.is_active.is_(True),
            (ApiToken.expires_at.is_(None) | (ApiToken.expires_at > now)),
        )
    )
    return cast(ApiToken | None, record)


def build_ci_response(
    *,
    status: Any | None = None,
    checks: Sequence[Mapping[str, Any]] | None = None,
    message: str | None = None,
    token_name: str | None = None,
) -> dict[str, Any]:
    computed_status = normalize_ci_status(status)
    if checks:
        computed_status = summarize_ci_status(checks)
    if computed_status == "PASS" and status is None:
        computed_status = "PASS"
    if message is None:
        message = {
            "PASS": "Regression check passed.",
            "WARN": "Regression check produced warnings.",
            "BLOCK": "Regression check blocked launch.",
        }[computed_status]
    return {
        "status": computed_status,
        "passed": computed_status == "PASS",
        "message": message,
        "checks": list(checks or []),
        "api_token": token_name,
    }
