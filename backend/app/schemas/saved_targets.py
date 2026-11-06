"""Saved target schemas (M13).

A saved target is the connector shape GreenLit detected for an app: where it
lives, what request to send and where the answer is read from. Extra fields are
rejected so a client cannot smuggle a header value (or a permission record) into
a row that the UI presents as harmless.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.runs import ResponseFormat


class SavedTargetCreate(BaseModel):
    """Everything the panel asks for; the service validates the name and URL."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2000)
    method: str = Field(default="POST", max_length=10)
    body_template: str | None = Field(default=None, max_length=20_000)
    # Names only: a saved target holds no header value at all.
    header_names: list[str] = Field(default_factory=list, max_length=60)
    answer_path: str | None = Field(default=None, max_length=300)
    context_path: str | None = Field(default=None, max_length=300)
    stream_content_path: str | None = Field(default=None, max_length=300)
    response_format: ResponseFormat = "json"
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    max_concurrency: int = Field(default=1, ge=1, le=8)
    min_delay_ms: int = Field(default=500, ge=0, le=60_000)
    max_retries: int = Field(default=3, ge=0, le=10)
    allow_private_targets: bool = False


class SavedTargetUpdate(BaseModel):
    """A partial edit: only the fields present in the body change.

    An explicit ``null`` clears an optional field (a target that no longer
    returns context, say), which is why every field defaults to "unset" rather
    than to null.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=2000)
    method: str | None = Field(default=None, max_length=10)
    body_template: str | None = Field(default=None, max_length=20_000)
    header_names: list[str] | None = Field(default=None, max_length=60)
    answer_path: str | None = Field(default=None, max_length=300)
    context_path: str | None = Field(default=None, max_length=300)
    stream_content_path: str | None = Field(default=None, max_length=300)
    response_format: ResponseFormat | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_concurrency: int | None = Field(default=None, ge=1, le=8)
    min_delay_ms: int | None = Field(default=None, ge=0, le=60_000)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    allow_private_targets: bool | None = None


class SavedTargetRead(BaseModel):
    """A saved target as the Settings panel shows it."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    name: str
    connector_type: str
    url: str
    method: str
    body_template: str | None = None
    header_names: list[str] = Field(default_factory=list)
    answer_path: str | None = None
    context_path: str | None = None
    stream_content_path: str | None = None
    response_format: str
    timeout_seconds: int
    max_concurrency: int
    min_delay_ms: int
    max_retries: int
    allow_private_targets: bool
    created_at: datetime
    updated_at: datetime


class SavedTargetListResponse(BaseModel):
    items: list[SavedTargetRead]
    total: int
