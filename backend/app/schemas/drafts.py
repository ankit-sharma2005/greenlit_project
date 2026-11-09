"""Draft dataset generation and review schemas (PART 1, phase 3).

A draft is generated, reviewed item by item, and only then published. Nothing in
these schemas can touch a dataset version directly: `publish` is a separate call
that copies approved items into a new version.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DraftKind = Literal["document_fact", "unanswerable", "paraphrase", "edge_case"]
ItemStatus = Literal["pending", "approved", "rejected"]


class DraftCreateRequest(BaseModel):
    """Ask for a new draft. The generator may be the account's default."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    app_description: str = Field(min_length=1, max_length=4_000)
    count: int = Field(default=10, ge=1, le=50)
    kinds: list[DraftKind] = Field(default=["document_fact"])
    documents: str | None = Field(default=None, max_length=20_000)
    provider_id: uuid.UUID | None = None
    model: str | None = Field(default=None, max_length=200)


class DraftItemUpdate(BaseModel):
    """Review one item: change its status, its text, or both."""

    model_config = ConfigDict(extra="forbid")

    status: ItemStatus | None = None
    question: str | None = Field(default=None, min_length=1, max_length=500)
    expected_answer: str | None = Field(default=None, min_length=1, max_length=2_000)
    source_passage: str | None = Field(default=None, max_length=1_000)


class DraftItemRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    row_index: int
    question: str
    expected_answer: str
    source_passage: str | None = None
    kind: str
    status: str
    edited: bool
    generated_by_model: str
    generator_provider: str
    prompt_version: str
    reviewed_at: datetime | None = None


class DraftRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    name: str
    app_description: str
    requested_count: int
    kinds: list[str]
    generator_provider_id: uuid.UUID | None = None
    generator_provider_name: str
    generated_by_model: str
    prompt_version: str
    """True when the generator is the same provider and model as the judge."""
    same_as_judge: bool
    status: str
    published_dataset_id: uuid.UUID | None = None
    published_version_id: uuid.UUID | None = None
    created_at: datetime
    items: list[DraftItemRead] = Field(default_factory=list)


class DraftListResponse(BaseModel):
    items: list[DraftRead]
    total: int


class DraftCounts(BaseModel):
    """Reviewer counters, so the UI never computes a percentage the server did not."""

    total: int
    pending: int
    approved: int
    rejected: int
