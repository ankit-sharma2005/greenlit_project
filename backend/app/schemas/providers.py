"""Provider schemas. Extra fields are rejected."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProviderBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=40)
    model_name: str = Field(min_length=1, max_length=120)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    backoff_factor: float = Field(default=2.0, ge=1.0, le=10.0)
    rate_limit_per_minute: int | None = Field(default=None, ge=1)
    tokens_per_minute: int | None = Field(default=None, ge=1)
    is_active: bool = Field(default=True)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # M3: connector type selection
    connector: str = Field(
        default="http_endpoint",
        pattern="^(http_endpoint|prompt_app|upload_outputs|csv|json|http_endpoint)$",
        description="Connector type for test configuration",
    )


class ProviderCreate(ProviderBase):
    pass


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    kind: str | None = None
    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    backoff_factor: float | None = None
    rate_limit_per_minute: int | None = None
    tokens_per_minute: int | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None
    connector: str | None = None


class ProviderRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    name: str
    kind: str
    model_name: str
    base_url: str | None = None
    api_key: str | None = None  # Never returned - encrypted at rest
    timeout_seconds: int
    max_retries: int
    backoff_factor: float
    rate_limit_per_minute: int | None = None
    tokens_per_minute: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    connector: str | None = None  # M3: stored per-provider


class ProviderTestConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    message: str
    latency_ms: int | None = None
    model: str | None = None
    fields: dict[str, Any] | None = None  # M3: prompt/app fields or upload config
    is_free_tier: bool | None = None
    privacy_warning: str | None = None
    connector: str | None = None  # M3: which connector was used
