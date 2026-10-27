"""M5 rule metrics: pure functions over one item trace or a whole run.

Every metric returns a :class:`MetricResult` with a score in ``0..1``, a
pass/fail flag, a plain-language explanation and an ``instrumented`` flag.
A metric whose input the app never reported ("not instrumented") is excluded
from the weighted score — never counted as zero.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

DEFAULT_LATENCY_LIMIT_MS = 5000
DEFAULT_LATENCY_PASS_SHARE = 0.9
DEFAULT_ERROR_RATE_LIMIT = 0.05
DEFAULT_TIMEOUT_RATE_LIMIT = 0.05
DEFAULT_TOKEN_COVERAGE = 0.9

STOPWORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "she",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class MetricResult:
    """One metric's outcome for a run."""

    name: str
    score: float
    passed: bool
    explanation: str
    instrumented: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 4),
            "passed": self.passed,
            "explanation": self.explanation,
            "instrumented": self.instrumented,
            "details": self.details,
        }


def not_instrumented(name: str, reason: str) -> MetricResult:
    """A metric that cannot be measured is reported, not scored."""
    return MetricResult(
        name=name,
        score=0.0,
        passed=False,
        explanation=f"not instrumented: {reason}",
        instrumented=False,
    )


def content_tokens(text: str) -> set[str]:
    """Lower-case, strip punctuation and stopwords, keep content words."""
    return {token for token in _TOKEN_RE.findall(text.lower()) if token not in STOPWORDS}


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile; ``p`` is a fraction such as 0.95."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile needs at least one value")
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def output_nonempty(output: str | None, threshold: float = 1.0) -> MetricResult:
    """The app returned something a user could read."""
    if output is None:
        return MetricResult(
            name="output_nonempty",
            score=0.0,
            passed=False,
            explanation="the app returned no output at all",
        )
    score = 1.0 if output.strip() else 0.0
    return MetricResult(
        name="output_nonempty",
        score=score,
        passed=score >= threshold,
        explanation=(
            "the app returned a non-empty answer" if score else "the app returned an empty answer"
        ),
    )


def answer_match(output: str | None, expected: str | None, threshold: float = 0.6) -> MetricResult:
    """Share of the expected answer's content words present in the output.

    Deliberately not string equality: paraphrases and extra words still count.
    A minimum shared-content-word gate stops two unrelated long answers from
    scoring above zero.
    """
    if expected is None or not expected.strip():
        return not_instrumented("answer_match", "this case has no expected answer")
    expected_tokens = content_tokens(expected)
    if not expected_tokens:
        return not_instrumented("answer_match", "the expected answer has no content words")
    got = content_tokens(output or "")
    shared = expected_tokens & got
    if not shared:
        return MetricResult(
            name="answer_match",
            score=0.0,
            passed=False,
            explanation="the answer shares no content words with the expected answer",
            details={"expected_tokens": len(expected_tokens), "shared_tokens": 0},
        )
    score = len(shared) / len(expected_tokens)
    return MetricResult(
        name="answer_match",
        score=score,
        passed=score >= threshold,
        explanation=(
            f"the answer contains {len(shared)} of the {len(expected_tokens)} "
            "content words in the expected answer"
        ),
        details={"expected_tokens": len(expected_tokens), "shared_tokens": len(shared)},
    )


# Connectors report "no retrieval data" as this literal string, not as None.
NOT_INSTRUMENTED_SENTINEL = "not instrumented"


def _is_sentinel(value: str) -> bool:
    """True for the connectors' literal "not instrumented" marker."""
    return value.strip().lower() == NOT_INSTRUMENTED_SENTINEL


def retrieval_context_recall(
    retrieved_context: Sequence[str] | str | None,
    reference_context: Sequence[str] | str | None,
    threshold: float = 0.6,
) -> MetricResult:
    """Share of reference-context content words found in the retrieved context."""
    if retrieved_context is None or (
        isinstance(retrieved_context, str) and _is_sentinel(retrieved_context)
    ):
        return not_instrumented(
            "retrieval_context_recall", "the app did not return retrieved context"
        )
    if reference_context is None:
        return not_instrumented("retrieval_context_recall", "this case has no reference context")
    reference_tokens = content_tokens(_join(reference_context))
    if not reference_tokens:
        return not_instrumented(
            "retrieval_context_recall", "the reference context has no content words"
        )
    retrieved_tokens = content_tokens(_join(retrieved_context))
    shared = reference_tokens & retrieved_tokens
    score = len(shared) / len(reference_tokens)
    return MetricResult(
        name="retrieval_context_recall",
        score=score,
        passed=score >= threshold,
        explanation=(
            f"retrieval found {len(shared)} of the {len(reference_tokens)} content words "
            "the correct context needs"
        ),
        details={"reference_tokens": len(reference_tokens), "shared_tokens": len(shared)},
    )


def latency_under_limit(
    latencies: Sequence[int | None],
    limit_ms: int = DEFAULT_LATENCY_LIMIT_MS,
    min_share: float = DEFAULT_LATENCY_PASS_SHARE,
) -> MetricResult:
    """Share of answers faster than ``limit_ms``; also reports p50 and p95."""
    measured = [float(value) for value in latencies if value is not None]
    if not measured:
        return not_instrumented("latency_under_limit", "no timings were recorded")
    under = sum(1 for value in measured if value <= limit_ms)
    score = under / len(measured)
    p50 = percentile(measured, 0.50)
    p95 = percentile(measured, 0.95)
    return MetricResult(
        name="latency_under_limit",
        score=score,
        passed=score >= min_share,
        explanation=(
            f"{under} of {len(measured)} answers arrived within {limit_ms} ms "
            f"(p50 {p50:.0f} ms, p95 {p95:.0f} ms)"
        ),
        details={
            "limit_ms": limit_ms,
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "max_ms": round(max(measured), 1),
        },
    )


def error_rate(
    errors: Sequence[str | None], limit: float = DEFAULT_ERROR_RATE_LIMIT
) -> MetricResult:
    """Share of items that came back without an error."""
    if not errors:
        return not_instrumented("error_rate", "there were no items to check")
    failed = sum(1 for error in errors if error)
    rate = failed / len(errors)
    score = 1.0 - rate
    return MetricResult(
        name="error_rate",
        score=score,
        passed=rate <= limit,
        explanation=f"{failed} of {len(errors)} items returned an error",
        details={"error_rate": round(rate, 4), "allowed_rate": limit},
    )


def timeout_rate(
    timeouts: Sequence[bool], limit: float = DEFAULT_TIMEOUT_RATE_LIMIT
) -> MetricResult:
    """Share of items that did not time out."""
    if not timeouts:
        return not_instrumented("timeout_rate", "there were no items to check")
    timed_out = sum(1 for timed_out_item in timeouts if timed_out_item)
    rate = timed_out / len(timeouts)
    score = 1.0 - rate
    return MetricResult(
        name="timeout_rate",
        score=score,
        passed=rate <= limit,
        explanation=f"{timed_out} of {len(timeouts)} items timed out",
        details={"timeout_rate": round(rate, 4), "allowed_rate": limit},
    )


def token_usage_present(
    token_pairs: Sequence[tuple[int | None, int | None]],
    min_share: float = DEFAULT_TOKEN_COVERAGE,
) -> MetricResult:
    """Share of items that reported both token counts."""
    if not token_pairs:
        return not_instrumented("token_usage_present", "there were no items to check")
    reported = sum(
        1
        for tokens_in, tokens_out in token_pairs
        if tokens_in is not None and tokens_out is not None
    )
    if reported == 0:
        return not_instrumented("token_usage_present", "the app does not report token usage")
    score = reported / len(token_pairs)
    return MetricResult(
        name="token_usage_present",
        score=score,
        passed=score >= min_share,
        explanation=f"{reported} of {len(token_pairs)} items reported token usage",
    )


def output_json_schema_valid(
    output: str | None, schema: Mapping[str, Any] | None, threshold: float = 1.0
) -> MetricResult:
    """The output parses as JSON and matches the expected shape."""
    if schema is None:
        return not_instrumented(
            "output_json_schema_valid", "no JSON schema was supplied for this case"
        )
    if output is None or not output.strip():
        return MetricResult(
            name="output_json_schema_valid",
            score=0.0,
            passed=False,
            explanation="there was no output to check against the schema",
        )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        return MetricResult(
            name="output_json_schema_valid",
            score=0.0,
            passed=False,
            explanation=f"the output is not valid JSON: {exc.msg} at position {exc.pos}",
        )
    problem = _schema_problem(payload, schema, "$")
    if problem:
        return MetricResult(
            name="output_json_schema_valid",
            score=0.0,
            passed=False,
            explanation=f"the output does not match the schema: {problem}",
        )
    return MetricResult(
        name="output_json_schema_valid",
        score=1.0,
        passed=True,
        explanation="the output is valid JSON and matches the schema",
    )


def tool_call_match(
    tool_calls: Sequence[Any] | None,
    expected_tool_calls: Sequence[Any] | None,
    threshold: float = 0.8,
) -> MetricResult:
    """Overlap between the expected tool names and the calls the app made."""
    if expected_tool_calls is None:
        return not_instrumented("tool_call_match", "this case has no expected tool calls")
    if tool_calls is None:
        return not_instrumented("tool_call_match", "the app did not return tool calls")
    expected = _tool_names(expected_tool_calls)
    actual = _tool_names(tool_calls)
    if not expected and not actual:
        return MetricResult(
            name="tool_call_match",
            score=1.0,
            passed=True,
            explanation="no tool call was expected and none was made",
        )
    if not expected:
        return MetricResult(
            name="tool_call_match",
            score=0.0,
            passed=False,
            explanation=(
                "no tool call was expected but the app called " + ", ".join(sorted(actual))
            ),
        )
    union = expected | actual
    score = len(expected & actual) / len(union) if union else 1.0
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    parts = []
    if missing:
        parts.append("missing " + ", ".join(missing))
    if extra:
        parts.append("unexpected " + ", ".join(extra))
    return MetricResult(
        name="tool_call_match",
        score=score,
        passed=score >= threshold,
        explanation=(
            "tool calls match the expectation"
            if not parts
            else "tool calls differ: " + "; ".join(parts)
        ),
        details={"expected": sorted(expected), "actual": sorted(actual)},
    )


@dataclass(frozen=True)
class ItemTrace:
    """One case: what the app was asked, what it returned, what was expected."""

    input: str
    output: str | None = None
    expected_answer: str | None = None
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

    @property
    def valid(self) -> bool:
        """An item counts as valid when the app produced some output."""
        return self.output is not None and self.output.strip() != ""


ITEM_METRICS = (
    "output_nonempty",
    "answer_match",
    "retrieval_context_recall",
    "output_json_schema_valid",
    "tool_call_match",
)


def evaluate_item(
    item: ItemTrace, thresholds: Mapping[str, float] | None = None
) -> dict[str, MetricResult]:
    """Run every per-item metric on one trace."""
    limits = thresholds or {}
    return {
        "output_nonempty": output_nonempty(item.output, limits.get("output_nonempty", 1.0)),
        "answer_match": answer_match(
            item.output, item.expected_answer, limits.get("answer_match", 0.6)
        ),
        "retrieval_context_recall": retrieval_context_recall(
            item.retrieved_context,
            item.reference_context,
            limits.get("retrieval_context_recall", 0.6),
        ),
        "output_json_schema_valid": output_json_schema_valid(
            item.output, item.output_schema, limits.get("output_json_schema_valid", 1.0)
        ),
        "tool_call_match": tool_call_match(
            item.tool_calls,
            item.expected_tool_calls,
            limits.get("tool_call_match", 0.8),
        ),
    }


def evaluate_items(
    items: Sequence[ItemTrace],
    thresholds: Mapping[str, float] | None = None,
    latency_limit_ms: int = DEFAULT_LATENCY_LIMIT_MS,
    extra: Mapping[str, MetricResult] | None = None,
) -> dict[str, MetricResult]:
    """Average the per-item metrics and add the run-level operations metrics.

    ``extra`` carries metrics measured elsewhere (the built-in safety probes),
    merged last so a run scores quality, operations and safety in one place.
    """
    limits = thresholds or {}
    per_item = [evaluate_item(item, limits) for item in items]
    results: dict[str, MetricResult] = {}

    for metric_name in ITEM_METRICS:
        measured = [
            item_results[metric_name]
            for item_results in per_item
            if item_results[metric_name].instrumented
        ]
        if not measured:
            reason = _not_instrumented_reason(items, metric_name)
            results[metric_name] = not_instrumented(metric_name, reason)
            continue
        average = sum(result.score for result in measured) / len(measured)
        passed_count = sum(1 for result in measured if result.passed)
        threshold = _threshold_for(metric_name, limits)
        results[metric_name] = MetricResult(
            name=metric_name,
            score=average,
            passed=average >= threshold,
            explanation=(
                f"{passed_count} of {len(measured)} measured cases passed; "
                f"average score {average:.2f}"
            ),
            details={
                "measured_cases": len(measured),
                "passed_cases": passed_count,
                "threshold": threshold,
            },
        )

    results["latency_under_limit"] = latency_under_limit(
        [item.latency_ms for item in items],
        latency_limit_ms,
        limits.get("latency_under_limit", DEFAULT_LATENCY_PASS_SHARE),
    )
    results["error_rate"] = error_rate(
        [item.error for item in items], limits.get("error_rate", DEFAULT_ERROR_RATE_LIMIT)
    )
    results["timeout_rate"] = timeout_rate(
        [item.timed_out for item in items],
        limits.get("timeout_rate", DEFAULT_TIMEOUT_RATE_LIMIT),
    )
    results["token_usage_present"] = token_usage_present(
        [(item.tokens_in, item.tokens_out) for item in items],
        limits.get("token_usage_present", DEFAULT_TOKEN_COVERAGE),
    )
    if extra:
        results.update(extra)
    return results


def failed_cases(
    items: Sequence[ItemTrace], thresholds: Mapping[str, float] | None = None
) -> list[dict[str, str]]:
    """Cases whose answer was wrong, empty or errored, with a plain reason."""
    failures: list[dict[str, str]] = []
    for item in items:
        results = evaluate_item(item, thresholds)
        reasons: list[str] = []
        if item.error:
            reasons.append(f"the app returned an error: {item.error}")
        if item.timed_out:
            reasons.append("the app did not answer before the timeout")
        for metric_name in ITEM_METRICS:
            result = results[metric_name]
            if result.instrumented and not result.passed:
                reasons.append(f"{metric_name}: {result.explanation}")
        if reasons:
            failures.append(
                {
                    "input": item.input,
                    "expected": item.expected_answer or "",
                    "actual": (item.output or "").strip() or "(empty)",
                    "reason": "; ".join(reasons),
                }
            )
    return failures


def _join(context: Sequence[str] | str) -> str:
    if isinstance(context, str):
        return context
    return " ".join(str(part) for part in context)


def _tool_names(calls: Sequence[Any]) -> set[str]:
    names: set[str] = set()
    for call in calls:
        if isinstance(call, str):
            names.add(call)
            continue
        if isinstance(call, Mapping):
            name = call.get("name")
            function = call.get("function")
            if name is None and isinstance(function, Mapping):
                name = function.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return names


def _schema_problem(value: Any, schema: Mapping[str, Any], path: str) -> str | None:
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _type_matches(value, expected_type):
        return f"{path} should be {expected_type} but is {type(value).__name__}"
    if isinstance(value, Mapping):
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    return f"{path}.{key} is required but missing"
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            for key, subschema in properties.items():
                if key in value and isinstance(subschema, Mapping):
                    problem = _schema_problem(value[key], subschema, f"{path}.{key}")
                    if problem:
                        return problem
    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, entry in enumerate(value):
                problem = _schema_problem(entry, item_schema, f"{path}[{index}]")
                if problem:
                    return problem
    return None


def _type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, Mapping)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _threshold_for(metric_name: str, thresholds: Mapping[str, float]) -> float:
    defaults = {
        "output_nonempty": 1.0,
        "answer_match": 0.6,
        "retrieval_context_recall": 0.6,
        "output_json_schema_valid": 1.0,
        "tool_call_match": 0.8,
    }
    return thresholds.get(metric_name, defaults[metric_name])


def _not_instrumented_reason(items: Sequence[ItemTrace], metric_name: str) -> str:
    if not items:
        return "there were no items"
    if metric_name == "retrieval_context_recall":
        return "the app did not return retrieved context"
    if metric_name == "output_json_schema_valid":
        return "no JSON schema was supplied"
    if metric_name == "tool_call_match":
        return "the app did not return tool calls"
    if metric_name == "answer_match":
        return "no case had an expected answer"
    return "no case could be measured"
