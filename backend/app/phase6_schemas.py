from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    reason: str = Field(min_length=3, max_length=1000)


class BaselineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    workspace_id: UUID
    run_id: UUID
    approved_by: UUID
    reason: str
    updated_at: datetime


class MetricComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    category: str
    baseline_mean: float
    candidate_mean: float
    delta: float
    confidence_interval: tuple[float, float]
    paired_permutation_p_value: float
    holm_adjusted_p_value: float
    mcnemar_p_value: float
    sample_size: int
    wins: int
    ties: int
    losses: int
    significant: bool
    classification: Literal["improved", "no_significant_change", "regressed"]


class RunComparisonOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_run_id: UUID
    candidate_run_id: UUID
    outcome: Literal[
        "significant_difference", "no_significant_difference", "insufficient_data"
    ]
    confidence_level: float
    metrics: list[MetricComparison]
    warnings: list[str]


class RegressionFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_item_id: UUID
    position: int
    metric: str
    baseline_score: float
    candidate_score: float
    regression_critical: bool


class RegressionReportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_run_id: UUID
    candidate_run_id: UUID
    status: Literal["PASS", "WARN", "BLOCK"]
    reasons: list[str]
    new_failures: list[RegressionFailure]
    comparison: RunComparisonOut
