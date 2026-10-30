"""Schemas for the metrics/decision preview API (M5)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CaseIn(BaseModel):
    """One case: the question, the expected answer and what the app returned."""

    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=0, max_length=20_000)
    expected_answer: str | None = None
    output: str | None = None
    retrieved_context: list[str] | str | None = None
    reference_context: list[str] | str | None = None
    tool_calls: list[Any] | None = None
    expected_tool_calls: list[Any] | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    tokens_in: int | None = Field(default=None, ge=0)
    tokens_out: int | None = Field(default=None, ge=0)
    error: str | None = None
    timed_out: bool = False
    output_schema: dict[str, Any] | None = None


class JudgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unavailable_items: int = Field(default=0, ge=0)
    low_confidence_items: int = Field(default=0, ge=0)
    disagreements: int = Field(default=0, ge=0)
    tolerance: int = Field(default=0, ge=0)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = "plain_chatbot"
    cases: list[CaseIn] | None = None
    csv: str | None = None
    file_format: Literal["csv", "json", "jsonl"] = "csv"
    latency_limit_ms: int = Field(default=5000, ge=1, le=600_000)
    judge: JudgeIn = Field(default_factory=JudgeIn)


class MetricOut(BaseModel):
    name: str
    score: float
    passed: bool
    explanation: str
    instrumented: bool
    weight: float
    threshold: float
    hard_gate: bool
    details: dict[str, Any] = Field(default_factory=dict)


class FailedCaseOut(BaseModel):
    input: str
    expected: str
    actual: str
    reason: str
    # Structured detail, when the connector or gateway recorded one.
    error_kind: str | None = None
    http_status: int | None = None
    target: str | None = None
    error_snippet: str | None = None
    error_summary: str | None = None


class PreviewResponse(BaseModel):
    profile: str
    profile_name: str
    verdict: str
    score: float | None
    rule: int
    reason: str
    review_threshold: float
    go_threshold: float
    suggested_fixes: list[str]
    metrics: list[MetricOut]
    failed_cases: list[FailedCaseOut]
    item_count: int
    valid_items: int


class TemplateOut(BaseModel):
    key: str
    name: str
    description: str
    review_threshold: float
    go_threshold: float
    criteria: list[dict[str, Any]]


class TemplatesResponse(BaseModel):
    templates: list[TemplateOut]
    default: str
