from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.phase4_schemas import MetricScoreOut

VERDICT_CATEGORIES = frozenset({"quality", "rag", "tool", "operational"})
VERDICT_METRICS = frozenset(
    {
        "output_nonempty",
        "answer_match",
        "answer_exact_match",
        "retrieval_context_recall",
        "tool_call_match",
        "latency_under_5s",
        "token_usage_present",
        "output_json_schema_valid",
        "answer_quality",
    }
)
DEFAULT_VERDICT_CRITERIA: dict[str, object] = {
    "go_threshold": 0.8,
    "review_threshold": 0.6,
    "category_weights": {
        "quality": 1.0,
        "rag": 1.0,
        "tool": 1.0,
        "operational": 1.0,
    },
    "hard_gates": {},
}


class VerdictCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    go_threshold: float = Field(default=0.8, ge=0, le=1)
    review_threshold: float = Field(default=0.6, ge=0, le=1)
    category_weights: dict[str, float] = Field(
        default_factory=lambda: {
            str(category): 1.0 for category in sorted(VERDICT_CATEGORIES)
        },
        max_length=4,
    )
    hard_gates: dict[str, float] = Field(default_factory=dict, max_length=8)

    @model_validator(mode="after")
    def validate_criteria(self) -> VerdictCriteria:
        if self.review_threshold > self.go_threshold:
            raise ValueError("review_threshold must not exceed go_threshold")
        unknown_categories = set(self.category_weights) - VERDICT_CATEGORIES
        if unknown_categories:
            raise ValueError(
                f"Unknown score categories: {', '.join(sorted(unknown_categories))}"
            )
        if any(not 0 < weight <= 10 for weight in self.category_weights.values()):
            raise ValueError("Category weights must be greater than 0 and at most 10")
        unknown_metrics = set(self.hard_gates) - VERDICT_METRICS
        if unknown_metrics:
            raise ValueError(
                f"Unknown hard-gate metrics: {', '.join(sorted(unknown_metrics))}"
            )
        return self


class CategoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    score: float
    weight: float
    metric_count: int


class ReadinessIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: str
    message: str
    run_item_id: str | None = None


class ReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "needs_attention"]
    issues: list[ReadinessIssue]


class RunVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["GO", "REVIEW", "NO_GO"]
    score: float | None = Field(default=None, ge=0, le=1)
    summary: str
    reasons: list[str]
    categories: list[CategoryResult]
    readiness: ReadinessReport


class RunReportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    dataset_item_id: str
    position: int
    status: str
    category: str
    regression_critical: bool
    input: str
    reference_answer: str | None
    output: str | None
    trace: dict[str, object]
    scores: list[MetricScoreOut]
    error: str | None


class RunReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_name: str
    dataset_id: str
    dataset_name: str
    dataset_version: int
    dataset_hash: str
    connector_type: str | None
    provider_id: str | None
    provider_name: str | None
    provider_type: str | None
    model: str | None
    run_created_at: str
    run_started_at: str | None
    run_finished_at: str | None
    app_version_id: str
    app_version: int
    settings: dict[str, object]


class RunReportMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: str
    method: str
    mean_score: float | None
    scored_cases: int
    status_counts: dict[str, int]
    hard_gate_threshold: float | None
    hard_gate_failures: int


class RunReportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    metadata: RunReportMetadata
    criteria: VerdictCriteria
    rules_applied: VerdictCriteria
    verdict: RunVerdict
    metrics: list[RunReportMetric]
    items: list[RunReportItem]
    failed_cases: list[RunReportItem]
    safety_results: dict[str, object]
    regression_vs_baseline: dict[str, object]
    calibration_summary: dict[str, object]
