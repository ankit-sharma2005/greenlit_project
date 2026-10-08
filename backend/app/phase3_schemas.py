from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.phase4_schemas import MetricScoreOut


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetColumnMapping(StrictModel):
    input_field: str = Field(min_length=1, max_length=200)
    reference_answer_field: str | None = Field(default=None, max_length=200)
    reference_context_field: str | None = Field(default=None, max_length=200)
    category_field: str | None = Field(default=None, max_length=200)
    split_field: str | None = Field(default=None, max_length=200)


class DatasetUploadMapping(DatasetColumnMapping):
    pass


class DatasetReviewRequest(StrictModel):
    item_ids: list[UUID] = Field(min_length=1, max_length=1000)
    review_status: Literal["approved", "rejected"]


class DatasetGenerationRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    template: Literal["rag", "chatbot", "agent", "extraction"]
    item_count: int = Field(ge=1, le=100)
    categories: list[Literal["normal", "edge", "adversarial", "safety"]] = Field(
        min_length=1, max_length=4
    )
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    language: str = Field(default="English", min_length=1, max_length=40)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    source_material: str = Field(default="", max_length=20_000)
    template_context: dict[str, object] = Field(default_factory=dict)
    provider_id: UUID
    model: str = Field(min_length=1, max_length=200)


class DatasetItemOut(BaseModel):
    id: UUID
    position: int
    input_text: str
    reference_answer: str | None
    reference_context: str | None
    category: str
    provenance: str
    review_status: str
    split: str
    data: dict[str, object]


class DatasetVersionOut(BaseModel):
    dataset_id: UUID
    dataset_name: str
    task_type: str
    version_id: UUID
    version: int
    content_hash: str
    total_items: int
    approved_items: int
    pending_items: int
    rejected_items: int
    split_counts: dict[str, int]
    category_counts: dict[str, int]
    locked_at: str | None
    validation_errors: list[dict[str, object]] = Field(default_factory=list)
    duplicate_count: int = 0
    items: list[DatasetItemOut] = Field(default_factory=list)


class EvalRunCreate(StrictModel):
    app_version_id: UUID
    dataset_version_id: UUID
    split: Literal["all", "dev", "test"] = "all"


class EvalRunOut(BaseModel):
    id: UUID
    project_id: UUID
    app_version_id: UUID
    dataset_version_id: UUID
    split: str
    status: str
    total_items: int
    completed_items: int
    failed_items: int
    pause_reason: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class EvalRunItemOut(BaseModel):
    id: UUID
    dataset_item_id: UUID
    status: str
    output: str | None
    trace: dict[str, object]
    scores: list[MetricScoreOut]
    error: str | None
    attempts: int
    completed_at: str | None
