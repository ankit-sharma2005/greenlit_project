"""Run and quick-test schemas (M6c)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.evaluation import FailedCaseOut, MetricOut

TestType = Literal["quality", "safety", "operations"]
EntryPoint = Literal["http_endpoint", "prompt_app", "upload_outputs"]

ALL_TEST_TYPES: list[TestType] = ["quality", "safety", "operations"]


class RunCreateRequest(BaseModel):
    """Start a run from saved settings: connector + approved dataset + criteria."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    entry_point: EntryPoint = "http_endpoint"
    target: str | None = Field(default=None, max_length=2000)
    test_types: list[TestType] = Field(default_factory=lambda: list(ALL_TEST_TYPES))

    dataset_id: UUID | None = None
    dataset_version_id: UUID | None = None
    criteria_profile: str | None = Field(default=None, max_length=60)

    # HTTP endpoint connector settings (persisted in the run's settings snapshot).
    method: str = Field(default="POST", max_length=10)
    body_template: str | None = Field(default=None, max_length=20_000)
    headers: dict[str, str] = Field(default_factory=dict)
    answer_path: str | None = Field(default=None, max_length=300)
    context_path: str | None = Field(default=None, max_length=300)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    allow_private_targets: bool = False

    # Prompt app connector settings.
    provider_id: UUID | None = None
    model: str | None = Field(default=None, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=20_000)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class QuickTestRequest(BaseModel):
    """Everything a CI job needs: entry point, target and the test types."""

    model_config = ConfigDict(extra="forbid")

    entry_point: EntryPoint = "http_endpoint"
    target: str = Field(min_length=1, max_length=2000)
    tests: list[TestType] = Field(default_factory=lambda: list(ALL_TEST_TYPES))

    # A dataset: an existing one, an inline CSV, or generate cases with the LLM.
    dataset_id: UUID | None = None
    csv: str | None = Field(default=None, max_length=2_000_000)
    generate: int = Field(default=20, ge=1, le=100)
    provider_id: UUID | None = None
    model: str | None = Field(default=None, max_length=120)

    # Connector settings auto-detect found, so the run asks the same way.
    method: str = Field(default="POST", max_length=10)
    body_template: str | None = Field(default=None, max_length=20_000)
    headers: dict[str, str] = Field(default_factory=dict)
    answer_path: str | None = Field(default=None, max_length=300)
    context_path: str | None = Field(default=None, max_length=300)

    timeout_seconds: int = Field(default=60, ge=1, le=300)
    allow_private_targets: bool = False
    name: str | None = Field(default=None, max_length=120)


class RunProgressRead(BaseModel):
    items_done: int = 0
    items_total: int = 0
    items_failed: int = 0
    items_cancelled: int = 0
    stage: str = "queued"
    started_at: str | None = None
    updated_at: str | None = None
    elapsed_seconds: float | None = None


class RunItemRead(BaseModel):
    row_index: int
    input_text: str
    state: str
    output: str | None = None
    error: str | None = None
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    trace: dict[str, object] | None = None


class RunItemsResponse(BaseModel):
    items: list[RunItemRead]
    total: int


class RunRead(BaseModel):
    id: UUID
    name: str
    entry_point: str
    state: str
    verdict: str | None = None
    score: float | None = None
    verdict_reason: str | None = None
    is_partial: bool = False
    criteria_profile: str
    test_types: list[str] = Field(default_factory=list)
    dataset_id: UUID | None = None
    dataset_version_id: UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: RunProgressRead = Field(default_factory=RunProgressRead)
    metrics: list[MetricOut] = Field(default_factory=list)
    failed_cases: list[FailedCaseOut] = Field(default_factory=list)


class RunListResponse(BaseModel):
    items: list[RunRead]
    total: int
    limit: int
    offset: int


class QuickTestResponse(BaseModel):
    run: RunRead
    dataset_id: UUID
    dataset_version_id: UUID
    generated: bool = False
