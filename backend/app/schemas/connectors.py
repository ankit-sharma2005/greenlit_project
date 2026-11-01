"""Connector schemas (M3)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ResponseFormat = Literal["json", "sse", "ndjson", "text"]


class CurlParseRequest(BaseModel):
    curl: str


class CurlParseResponse(BaseModel):
    """A parsed curl command: names only, never a header value or cookie."""

    method: str
    url: str
    header_names: list[str] = Field(default_factory=list)
    headers_secret: str | None = None
    body_template: str | None = None
    header_count: int = 0


class ConnectTestRequest(BaseModel):
    connector_type: str = Field(pattern="^(http_endpoint|prompt_app|upload_outputs)$")
    url: str | None = None
    method: str = "POST"
    body_template: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    # cURL-imported headers and cookies, already encrypted by the server.
    headers_secret: str | None = Field(default=None, max_length=20_000)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    allow_private_targets: bool = False
    max_concurrency: int = Field(default=1, ge=1, le=8)
    min_delay_ms: int = Field(default=500, ge=0, le=60_000)
    max_retries: int = Field(default=3, ge=0, le=10)
    answer_path: str | None = None
    context_path: str | None = None
    response_format: ResponseFormat = "json"
    stream_content_path: str | None = Field(default=None, max_length=300)
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
