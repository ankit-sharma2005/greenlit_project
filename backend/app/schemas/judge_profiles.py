"""Judge profile schemas (M7). Extra fields are rejected."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.judge import JUDGE_MAX_TOKENS


class JudgeProfileCreate(BaseModel):
    """Save a judge configuration; temperature is fixed at 0 by the service."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    provider_id: UUID | None = None
    model: str | None = Field(default=None, max_length=120)
    max_tokens: int = Field(default=JUDGE_MAX_TOKENS, ge=64, le=4096)
    # Cost guard: grade at most this many cases per run. Omitted or null grades
    # every case, which is the behaviour of a profile saved before the cap.
    max_cases: int | None = Field(default=None, ge=1, le=1000)


class JudgeProfileRead(BaseModel):
    """A saved profile plus the self-grading warnings for its current choice."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    provider_id: UUID | None = None
    provider_name: str | None = None
    model: str | None = None
    rubric_version: str
    temperature: float
    max_tokens: int
    max_cases: int | None = None
    is_selected: bool
    created_at: datetime
    updated_at: datetime
    warnings: list[str] = Field(default_factory=list)


class JudgeProfileListResponse(BaseModel):
    items: list[JudgeProfileRead]
    total: int
    selected_id: UUID | None = None
