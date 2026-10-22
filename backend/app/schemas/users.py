"""User administration schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.auth import UserRead


class UserListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[UserRead]
    total: int
    limit: int
    offset: int


class RoleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["admin", "member", "reviewer"]
