"""Dataset schemas.

Read models never expose ``raw_content``: the uploaded bytes stay in the database only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ColumnMappingRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    input_column: str
    output_column: str
    id_column: str | None = None
    retrieved_context_column: str | None = None
    latency_ms_column: str | None = None
    tokens_in_column: str | None = None
    tokens_out_column: str | None = None
    detected: bool


class DatasetVersionRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    dataset_id: UUID
    version_no: int
    content_hash: str
    row_count: int
    columns_snapshot: dict[str, Any] | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime


class DatasetRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    source_filename: str
    file_format: str
    content_hash: str
    created_at: datetime
    updated_at: datetime
    columns: ColumnMappingRead | None = None
    versions: list[DatasetVersionRead] = Field(default_factory=list)


class DatasetListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DatasetRead]
    total: int
    limit: int
    offset: int


class ColumnOverrides(BaseModel):
    """User-supplied column mapping; omitted fields are auto-detected."""

    model_config = ConfigDict(extra="forbid")

    input_column: str | None = Field(default=None, max_length=120)
    output_column: str | None = Field(default=None, max_length=120)
    id_column: str | None = Field(default=None, max_length=120)
    retrieved_context_column: str | None = Field(default=None, max_length=120)
    latency_ms_column: str | None = Field(default=None, max_length=120)
    tokens_in_column: str | None = Field(default=None, max_length=120)
    tokens_out_column: str | None = Field(default=None, max_length=120)


class DatasetUploadRequest(BaseModel):
    """The file itself travels as multipart; this carries the rest."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    column_overrides: ColumnOverrides | None = None
