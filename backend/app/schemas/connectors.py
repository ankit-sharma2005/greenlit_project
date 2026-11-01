"""Connector schemas (M3)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CurlParseRequest(BaseModel):
    curl: str


class CurlParseResponse(BaseModel):
    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str | None = None
    header_count: int = 0


class ConnectTestRequest(BaseModel):
    connector_type: str = Field(pattern="^(http_endpoint|prompt_app|upload_outputs)$")
    url: str | None = None
    method: str = "POST"
    body_template: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    allow_private_targets: bool = False
    max_concurrency: int = Field(default=1, ge=1, le=8)
    min_delay_ms: int = Field(default=500, ge=0, le=60_000)
    max_retries: int = Field(default=3, ge=0, le=10)
    answer_path: str | None = None
    context_path: str | None = None
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = 0.2
    auto_detect: bool = False
    column_overrides: dict[str, str] | None = None


class ConnectTestResponse(BaseModel):
    success: bool
    message: str
    trace: dict[str, Any] | None = None
    detected_answer_path: str | None = None
    detected_context_path: str | None = None
    detected_request_shape: str | None = None
