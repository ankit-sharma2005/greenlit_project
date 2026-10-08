from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewQueueEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    version: str = "unknown"
    status: Literal["queued", "reviewed"] = "queued"


class CalibrationSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_items: int
    cohens_kappa: float = Field(ge=-1, le=1)
    krippendorffs_alpha: float = Field(ge=-1, le=1)
    spearman_rho: float = Field(ge=-1, le=1)
    confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class BlindComparisonOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_label: str = "Variant A"
    right_label: str = "Variant B"
    blinded: bool = True
    delta: float
    winner: Literal["left", "right", "tie"]


class OverrideDecisionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    requires_justification: bool = True
    justification: str = ""
    audit_logged: bool = False


class FinalReportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["PASS", "WARN", "BLOCK", "READY"]
    item_count: int
    metric_means: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    rerun_without_live_calls: bool = True
