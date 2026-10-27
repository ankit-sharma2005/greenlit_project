"""Assemble metrics + decision for a preview request (M5)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.services.criteria import (
    CriteriaError,
    CriteriaProfile,
    get_profile,
    with_judge,
    with_safety,
)
from app.services.datasets import DatasetError, parse_rows
from app.services.decision import Decision, JudgeStatus, RunSummary, decide
from app.services.metrics import (
    ItemTrace,
    MetricResult,
    evaluate_items,
    failed_cases,
)


class EvaluationError(ValueError):
    """The preview request cannot be evaluated."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Preview:
    profile: CriteriaProfile
    decision: Decision
    metrics: tuple[MetricResult, ...]
    failures: tuple[Mapping[str, str], ...]
    item_count: int
    valid_items: int

    def metrics_by_name(self) -> dict[str, MetricResult]:
        return {result.name: result for result in self.metrics}


@dataclass(frozen=True)
class CaseData:
    """Loose case input, before it becomes an ItemTrace."""

    input: str
    expected_answer: str | None = None
    output: str | None = None
    retrieved_context: Sequence[str] | str | None = None
    reference_context: Sequence[str] | str | None = None
    tool_calls: Sequence[Any] | None = None
    expected_tool_calls: Sequence[Any] | None = None
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None
    timed_out: bool = False
    output_schema: Mapping[str, Any] | None = None


# Column names we accept from an uploaded file, most specific first.
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "input": ("input", "question", "prompt", "query"),
    "expected_answer": (
        "expected_answer",
        "expected",
        "reference_answer",
        "gold_answer",
        "ground_truth",
        "answer",
    ),
    "output": ("output", "actual_answer", "actual", "response", "prediction", "completion"),
    "retrieved_context": ("retrieved_context", "context", "contexts", "retrieved"),
    "reference_context": ("reference_context", "expected_context", "gold_context"),
    "latency_ms": ("latency_ms", "latency", "duration_ms"),
    "tokens_in": ("tokens_in", "prompt_tokens", "input_tokens"),
    "tokens_out": ("tokens_out", "completion_tokens", "output_tokens"),
    "error": ("error", "error_message"),
}


def cases_from_csv(raw: str, file_format: str = "csv") -> list[CaseData]:
    """Parse an uploaded outputs file into cases using auto-detected columns."""
    if not raw.strip():
        raise EvaluationError("The file is empty. Add at least an input and an output column.")
    try:
        _columns, rows = parse_rows(file_format, raw.encode("utf-8"))
    except DatasetError as exc:
        raise EvaluationError(exc.message) from exc
    if not rows:
        raise EvaluationError("The file has a header but no rows.")
    cases: list[CaseData] = []
    for row in rows:
        normalized = {str(key).strip().lower(): value for key, value in row.items()}
        values: dict[str, Any] = {}
        for field_name, aliases in _COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in normalized and normalized[alias] not in (None, ""):
                    values[field_name] = normalized[alias]
                    break
        if not values.get("input"):
            continue
        cases.append(
            CaseData(
                input=str(values["input"]),
                expected_answer=_optional_str(values.get("expected_answer")),
                output=_optional_str(values.get("output")),
                retrieved_context=_optional_str(values.get("retrieved_context")),
                reference_context=_optional_str(values.get("reference_context")),
                latency_ms=_optional_int(values.get("latency_ms")),
                tokens_in=_optional_int(values.get("tokens_in")),
                tokens_out=_optional_int(values.get("tokens_out")),
                error=_optional_str(values.get("error")),
            )
        )
    if not cases:
        raise EvaluationError(
            "No row had an input. Name the question column input, question or prompt."
        )
    return cases


def evaluate_preview(
    profile_key: str,
    cases: Sequence[CaseData],
    judge: JudgeStatus | None = None,
    latency_limit_ms: int = 5000,
    *,
    include_safety: bool = False,
    include_judge: bool = False,
    extra_metrics: Mapping[str, MetricResult] | None = None,
) -> Preview:
    """Score the cases with the profile's thresholds and decide the verdict.

    ``include_safety`` adds the built-in safety criteria to the profile (the
    Safety test type) and ``include_judge`` adds ``answer_quality`` (when the run
    is judged); ``extra_metrics`` carries results measured outside the items,
    such as the worker's safety probes or the judge's scores. Everything
    defaults to off, so a caller that mentions neither keeps the old behaviour.
    """
    if not cases:
        raise EvaluationError("Add at least one case with an input and an output.")
    try:
        base = get_profile(profile_key)
    except CriteriaError as exc:
        raise EvaluationError(exc.message) from exc
    profile = with_safety(base) if include_safety else base
    if include_judge:
        profile = with_judge(profile)

    items = [
        ItemTrace(
            input=case.input,
            output=case.output,
            expected_answer=case.expected_answer,
            retrieved_context=case.retrieved_context,
            reference_context=case.reference_context,
            tool_calls=case.tool_calls,
            expected_tool_calls=case.expected_tool_calls,
            latency_ms=case.latency_ms,
            tokens_in=case.tokens_in,
            tokens_out=case.tokens_out,
            error=case.error,
            timed_out=case.timed_out,
            output_schema=case.output_schema,
        )
        for case in cases
    ]

    thresholds = profile.thresholds()
    results = evaluate_items(items, thresholds, latency_limit_ms, extra_metrics)
    ordered = _ordered_results(results, profile)
    valid_items = sum(1 for item in items if item.valid)
    decision = decide(
        RunSummary(
            results=results,
            valid_items=valid_items,
            judge=judge or JudgeStatus(),
        ),
        profile,
    )
    return Preview(
        profile=profile,
        decision=decision,
        metrics=tuple(ordered),
        failures=tuple(failed_cases(items, thresholds)),
        item_count=len(items),
        valid_items=valid_items,
    )


def _ordered_results(
    results: Mapping[str, MetricResult], profile: CriteriaProfile
) -> list[MetricResult]:
    """Only the profile's metrics, in the profile's order."""
    ordered: list[MetricResult] = []
    for criterion in profile.criteria:
        result = results.get(criterion.metric)
        if result is not None:
            ordered.append(result)
    return ordered


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None
