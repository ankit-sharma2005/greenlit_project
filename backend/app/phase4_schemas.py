from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MetricCatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: str
    description: str
    requires: list[str]
    mode: Literal["reference_based", "reference_free"]
    method: Literal["rule", "llm_judge"]
    rubric_version: int


class MetricScoreOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: str
    method: Literal["rule", "llm_judge"]
    status: Literal["scored", "not_instrumented", "not_configured", "error"]
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str
    details: dict[str, object] = Field(default_factory=dict)
    judge_role: str | None = None
    rubric_version: int
    cache_hit: bool = False
