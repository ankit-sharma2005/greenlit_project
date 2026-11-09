"""Run and quick-test schemas (M6c)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.evaluation import FailedCaseOut, MetricOut

TestType = Literal["quality", "safety", "operations"]
EntryPoint = Literal["http_endpoint", "prompt_app", "upload_outputs", "mcp_server"]
# The static arguments an MCP tool call carries: a small object, not a payload.
MAX_MCP_EXTRA_ARGS_BYTES = 8_000
MAX_MCP_EXTRA_ARGS_KEYS = 40
ResponseFormat = Literal["json", "sse", "ndjson", "text"]

ALL_TEST_TYPES: list[TestType] = ["quality", "safety", "operations"]


class UploadOutputsColumnOverrides(BaseModel):
    """User-supplied column mapping for uploaded outputs.

    Omitted fields fall back to auto-detection from the CSV header row.
    """

    model_config = ConfigDict(extra="forbid")

    input_column: str | None = Field(default=None, max_length=120)
    output_column: str | None = Field(default=None, max_length=120)
    id_column: str | None = Field(default=None, max_length=120)
    retrieved_context_column: str | None = Field(default=None, max_length=120)
    latency_ms_column: str | None = Field(default=None, max_length=120)
    tokens_in_column: str | None = Field(default=None, max_length=120)
    tokens_out_column: str | None = Field(default=None, max_length=120)


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
    # cURL-imported headers and cookies, already encrypted by the server.
    headers_secret: str | None = Field(default=None, max_length=20_000)
    # Header names only: the target fingerprint is bound to which headers are
    # sent, never to a value the server cannot read back.
    header_names: list[str] | None = Field(default=None, max_length=60)
    answer_path: str | None = Field(default=None, max_length=300)
    context_path: str | None = Field(default=None, max_length=300)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    allow_private_targets: bool = False
    # Testing somebody else's app needs their permission, recorded with the run.
    permission_confirmed: bool = False
    permission_reference: str | None = Field(default=None, max_length=300)
    # Attack probes (safety) against a remote target need their own yes.
    safety_attacks_confirmed: bool = False
    # Polite-rate settings: one request at a time, 500 ms apart, three retries.
    max_concurrency: int = Field(default=1, ge=1, le=8)
    min_delay_ms: int = Field(default=500, ge=0, le=60_000)
    max_retries: int = Field(default=3, ge=0, le=10)
    # How the target answers: one JSON body, or a stream of events.
    response_format: ResponseFormat = "json"
    stream_content_path: str | None = Field(default=None, max_length=300)

    # MCP server connector settings (Streamable HTTP only; there is no stdio
    # field to accept, on purpose).
    mcp_tool: str | None = Field(default=None, min_length=1, max_length=120)
    # The tool argument the case's question is passed in; names are checked so a
    # value cannot smuggle a path or a JSON pointer.
    mcp_question_arg: str | None = Field(
        default=None, min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    # Fixed extra arguments, sent with every call. Values are treated as secrets
    # for display purposes: the report shows the names, never the values.
    mcp_extra_args: dict[str, Any] | None = None

    @field_validator("mcp_extra_args")
    @classmethod
    def _small_extra_args(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if len(value) > MAX_MCP_EXTRA_ARGS_KEYS:
            raise ValueError(f"at most {MAX_MCP_EXTRA_ARGS_KEYS} extra arguments are allowed")
        try:
            encoded = json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError) as exc:
            raise ValueError("the extra arguments must be JSON values") from exc
        if len(encoded.encode("utf-8")) > MAX_MCP_EXTRA_ARGS_BYTES:
            raise ValueError(
                f"the extra arguments must be under {MAX_MCP_EXTRA_ARGS_BYTES} bytes of JSON"
            )
        return value

    # Prompt app connector settings.
    provider_id: UUID | None = None
    model: str | None = Field(default=None, max_length=120)
    system_prompt: str | None = Field(default=None, max_length=20_000)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    # Upload outputs connector settings.
    column_overrides: UploadOutputsColumnOverrides | None = None

    # Judge settings: an explicit profile, else the selected one (Settings > Judge).
    judge_profile_id: UUID | None = None

    # Safety settings: which built-in sets to send. Omitted means every set.
    safety_sets: list[str] | None = Field(default=None, max_length=40)

    # Run caps (quirk 14). The worker stops the run when one is reached and
    # keeps what it already measured; the state becomes ``stopped_by_limit``.
    # ``max_cases`` has no default; the duration cap applies to every run.
    max_cases: int | None = Field(default=None, ge=1, le=1000)
    max_duration_seconds: int = Field(default=1800, ge=30, le=14_400)
    # Only enforced when the target reports tokens; never counted as 0.
    max_total_tokens: int | None = Field(default=None, ge=1, le=100_000_000)

    # STEP 2: a remote target needs an accepted first-contact check whose
    # settings fingerprint matches this run's. Local targets skip it.
    target_check_id: UUID | None = None
    # A smoke run is a short rehearsal: labelled, never a verdict or a baseline.
    is_smoke: bool = False


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
    headers_secret: str | None = Field(default=None, max_length=20_000)
    header_names: list[str] | None = Field(default=None, max_length=60)
    answer_path: str | None = Field(default=None, max_length=300)
    context_path: str | None = Field(default=None, max_length=300)

    timeout_seconds: int = Field(default=60, ge=1, le=300)
    allow_private_targets: bool = False
    permission_confirmed: bool = False
    permission_reference: str | None = Field(default=None, max_length=300)
    safety_attacks_confirmed: bool = False
    max_concurrency: int = Field(default=1, ge=1, le=8)
    min_delay_ms: int = Field(default=500, ge=0, le=60_000)
    max_retries: int = Field(default=3, ge=0, le=10)
    response_format: ResponseFormat = "json"
    stream_content_path: str | None = Field(default=None, max_length=300)
    name: str | None = Field(default=None, max_length=120)
    # Safety settings: which built-in sets to send. Omitted means every set.
    safety_sets: list[str] | None = Field(default=None, max_length=40)
    # The same run caps a normal run takes (quirk 14).
    max_cases: int | None = Field(default=None, ge=1, le=1000)
    max_duration_seconds: int = Field(default=1800, ge=30, le=14_400)
    max_total_tokens: int | None = Field(default=None, ge=1, le=100_000_000)
    # STEP 2: a remote quick test needs the same accepted target check.
    target_check_id: UUID | None = None
    is_smoke: bool = False


class RunPermissionRead(BaseModel):
    """Who allowed GreenLit to test this target; absent on local-app runs."""

    confirmed: bool = False
    reference: str | None = None
    safety_attacks_confirmed: bool = False


class RunLimitsRead(BaseModel):
    """The caps a run carried, and which one ended it (quirk 14)."""

    max_cases: int | None = None
    max_duration_seconds: int | None = None
    max_total_tokens: int | None = None
    # "max_cases", "max_duration_seconds" or "max_total_tokens" when a cap hit.
    stopped_by: str | None = None
    stop_reason: str | None = None
    # A token cap was set but no case reported tokens, so it could not apply.
    tokens_not_instrumented: bool = False


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
    # Derived from the stored answer at read time, never stored and never scored: the answer
    # contains text addressed to the judge. Shown on the case, changes no verdict.
    possible_judge_manipulation: bool = False


class RunItemsResponse(BaseModel):
    items: list[RunItemRead]
    total: int


class RunJudgeRead(BaseModel):
    """Which judge scored a run, with which rubric (spec 8.2)."""

    model: str | None = None
    provider_name: str | None = None
    profile_name: str | None = None
    rubric_version: str | None = None
    prompt_template_hash: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    # The profile's per-run cap (null grades every case), how many answerable
    # cases the run had, and how many the cap left out.
    max_cases: int | None = None
    case_total: int = 0
    capped_items: int = 0
    graded_items: int = 0
    unavailable_items: int = 0
    low_confidence_items: int = 0


class RegressionMetricRead(BaseModel):
    """One metric's before/after in a baseline comparison (spec 8.5)."""

    name: str
    baseline: float | None = None
    current: float | None = None
    delta: float | None = None
    passed_before: bool = False
    passed_now: bool = False
    hard_gate: bool = False
    regressed: bool = False


class RegressedCaseRead(BaseModel):
    row_index: int
    input: str


class RegressionRead(BaseModel):
    """How a finished run compares with the baseline for its dataset version."""

    status: str
    reason: str
    baseline_run_id: UUID | None = None
    baseline_run_name: str | None = None
    metric_tolerance: float
    case_tolerance: int
    metric_deltas: list[RegressionMetricRead] = Field(default_factory=list)
    regressed_metrics: list[str] = Field(default_factory=list)
    regressed_cases: list[RegressedCaseRead] = Field(default_factory=list)


class BaselineCreate(BaseModel):
    """Tolerances for the comparison; the defaults match the service."""

    model_config = ConfigDict(extra="forbid")

    metric_tolerance: float = Field(default=0.05, ge=0, le=1)
    case_tolerance: int = Field(default=2, ge=0, le=1000)


class BaselineRead(BaseModel):
    """The active baseline for one dataset version."""

    run_id: UUID
    run_name: str | None = None
    dataset_id: UUID | None = None
    dataset_version_id: UUID | None = None
    metric_tolerance: float
    case_tolerance: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OperationsRead(BaseModel):
    """How the app behaved during a run: speed, reliability and token use.

    Every rate and latency is ``None`` when it could not be measured, so the UI
    can say "not measured" instead of showing a misleading zero.
    """

    items_total: int = 0
    items_attempted: int = 0
    items_failed: int = 0
    items_cancelled: int = 0
    latency_samples: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    error_rate: float | None = None
    timeout_rate: float | None = None
    items_timed_out: int = 0
    retried_cases: int = 0
    tokens_in_total: int | None = None
    tokens_out_total: int | None = None
    price_per_1k_tokens_in: float | None = None
    price_per_1k_tokens_out: float | None = None
    cost_configured: bool = False
    cost_estimate: float | None = None


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
    permission: RunPermissionRead | None = None
    dataset_id: UUID | None = None
    dataset_version_id: UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: RunProgressRead = Field(default_factory=RunProgressRead)
    metrics: list[MetricOut] = Field(default_factory=list)
    failed_cases: list[FailedCaseOut] = Field(default_factory=list)
    judge: RunJudgeRead | None = None
    judge_skipped_reason: str | None = None
    # Set when a baseline exists for the run's dataset version (spec 8.5).
    regression: RegressionRead | None = None
    is_baseline: bool = False
    # Stored by the worker when the run finishes; absent on older runs.
    operations: OperationsRead | None = None
    # The caps the run carried; null on runs that predate them.
    limits: RunLimitsRead | None = None
    # A smoke run is labelled "Smoke run, not a verdict" and never a baseline.
    is_smoke: bool = False


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
