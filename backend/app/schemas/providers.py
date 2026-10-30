"""Provider schemas. Extra fields are rejected."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The two optional prices the rough cost estimate reads. They live in the
# provider's metadata bag so no migration was needed to introduce them.
PRICE_IN_KEY = "price_per_1k_tokens_in"
PRICE_OUT_KEY = "price_per_1k_tokens_out"
PRICE_KEYS: tuple[str, str] = (PRICE_IN_KEY, PRICE_OUT_KEY)


def normalize_provider_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Drop keys whose value is explicitly ``None``.

    ``None`` means "unset" for this bag, so a cleared price removes the key
    rather than storing a zero that would look like a free model.
    """
    if not metadata:
        return {}
    return {key: value for key, value in metadata.items() if value is not None}


def check_prices(metadata: dict[str, Any] | None) -> None:
    """Reject a price that is not a non-negative number.

    Raising ``ValueError`` here turns into the API's normal 422 with the field
    named, so the form can show the problem next to the input.
    """
    if not metadata:
        return
    for key in PRICE_KEYS:
        if key not in metadata:
            continue
        raw = metadata[key]
        if raw is None:
            continue
        if isinstance(raw, bool):
            raise ValueError(f"{key} must be a number, not a true/false value")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number") from None
        if value < 0:
            raise ValueError(f"{key} must be zero or greater")


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

    @model_validator(mode="after")
    def _validate_prices(self) -> ProviderBase:
        check_prices(self.metadata)
        return self


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

    @model_validator(mode="after")
    def _validate_prices(self) -> ProviderUpdate:
        check_prices(self.metadata)
        return self


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
    # The metadata bag, which is where the optional token prices live. It holds
    # no secrets: the API key is a separate column and is never returned.
    provider_config: dict[str, Any] | None = None


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
