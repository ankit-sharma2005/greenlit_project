"""Schemas for the review queue, human labels and calibration (M7)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Label = Literal["pass", "fail"]


class ReviewCaseRead(BaseModel):
    """One case a reviewer should look at, with the judge's own verdict."""

    run_item_id: UUID
    run_id: UUID
    run_name: str
    row_index: int
    input_text: str
    output: str | None = None
    judge_score: float | None = None
    judge_bucket: str | None = None
    judge_confidence: float | None = None
    judge_reason: str | None = None
    reasons: list[str] = Field(default_factory=list)
    label: str | None = None
    note: str | None = None


class ReviewQueueResponse(BaseModel):
    items: list[ReviewCaseRead]
    total: int


class LabelCreate(BaseModel):
    """A reviewer's verdict; the note is the only free text."""

    model_config = ConfigDict(extra="forbid")

    label: Label
    note: str | None = Field(default=None, max_length=2000)


class LabelRead(BaseModel):
    id: UUID
    run_id: UUID
    run_item_id: UUID
    reviewer_id: UUID
    label: str
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class CalibrationRead(BaseModel):
    """Raw agreement and Cohen's kappa against the human labels."""

    labelled: int
    agreed: int
    raw_agreement: float | None = None
    kappa: float | None = None
    reading: str
