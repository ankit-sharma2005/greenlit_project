"""Deterministic decision engine (spec 8.4): pure functions, no I/O.

Rules, first match wins:

1. a hard gate failed, or the run produced no valid items -> NO_GO
2. weighted score below ``review_threshold`` -> NO_GO
3. judge unavailable / low confidence / labels disagree -> REVIEW
4. weighted score below ``go_threshold`` -> REVIEW
5. otherwise -> GO
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.services.criteria import CriteriaProfile
from app.services.metrics import MetricResult

VERDICT_GO = "GO"
VERDICT_REVIEW = "REVIEW"
VERDICT_NO_GO = "NO_GO"

MAX_WEAK_METRICS = 3

SUGGESTED_FIXES: dict[str, str] = {
    "answer_match": (
        "answers do not contain the expected facts: check the prompt, the model "
        "and the retrieval step"
    ),
    "retrieval_context_recall": (
        "retrieval recall is low: check chunking, top-k and the embedding model"
    ),
    "output_nonempty": "some answers were empty: check the app's error handling and prompt",
    "latency_under_limit": "latency is high: reduce top-k or use a faster model",
    "error_rate": "the app returned errors: read the failed cases and fix that path",
    "timeout_rate": "requests timed out: raise the connector timeout or speed the app up",
    "token_usage_present": (
        "the app does not report token usage: return tokens_in and tokens_out in the trace"
    ),
    "output_json_schema_valid": (
        "the output does not match the expected JSON shape: fix the output format or the schema"
    ),
    "tool_call_match": (
        "expected tool calls are missing: check the tool-routing prompt and the tool definitions"
    ),
    "attack_resisted": (
        "the app gave in to a safety attack: add guardrails, keep secrets out of the "
        "system prompt, and treat retrieved text and tool output as untrusted"
    ),
    "over_refusal": (
        "the app refused harmless requests: loosen the safety wording so ordinary "
        "questions are still answered"
    ),
}


@dataclass(frozen=True)
class JudgeStatus:
    """What the judge module (M7) reports about this run."""

    unavailable_items: int = 0
    low_confidence_items: int = 0
    disagreements: int = 0
    tolerance: int = 0


@dataclass(frozen=True)
class Decision:
    verdict: str
    score: float | None
    rule: int
    reason: str
    review_threshold: float
    go_threshold: float
    weak_metrics: tuple[tuple[str, float], ...] = ()
    suggested_fixes: tuple[str, ...] = ()
    hard_gate_failures: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "score": None if self.score is None else round(self.score, 4),
            "rule": self.rule,
            "reason": self.reason,
            "review_threshold": self.review_threshold,
            "go_threshold": self.go_threshold,
            "weak_metrics": [
                {"metric": name, "score": round(score, 4)} for name, score in self.weak_metrics
            ],
            "suggested_fixes": list(self.suggested_fixes),
            "hard_gate_failures": list(self.hard_gate_failures),
        }


@dataclass(frozen=True)
class RunSummary:
    """Everything the decision needs, assembled by the caller."""

    results: Mapping[str, MetricResult]
    valid_items: int
    judge: JudgeStatus = field(default_factory=JudgeStatus)


def weighted_score(results: Mapping[str, MetricResult], profile: CriteriaProfile) -> float | None:
    """Weighted average over the metrics that were actually measurable."""
    numerator = 0.0
    denominator = 0.0
    for criterion in profile.criteria:
        result = results.get(criterion.metric)
        if result is None or not result.instrumented:
            continue
        numerator += criterion.weight * result.score
        denominator += criterion.weight
    if denominator == 0:
        return None
    return numerator / denominator


def decide(summary: RunSummary, profile: CriteriaProfile) -> Decision:
    """Apply the spec's rules in order and explain the verdict in plain words."""
    score = weighted_score(summary.results, profile)
    weak = _weak_metrics(summary.results, profile)
    gate_failures = _hard_gate_failures(summary.results, profile)
    review = profile.review_threshold
    go = profile.go_threshold

    # Rule 1: a hard gate, or nothing to score at all.
    if gate_failures:
        details = "; ".join(
            f"{name} scored {_format_score(summary.results[name].score)} "
            f"(needs {_format_score(_threshold(profile, name))})"
            for name in gate_failures
        )
        # The metric's own explanation names the cause (which attack, which
        # marker), so the verdict says what happened, not only which number moved.
        causes = " ".join(
            summary.results[name].explanation.strip() for name in gate_failures
        ).strip()
        reason = f"Hard gate failed: {details}. "
        if causes:
            reason += f"{causes} "
        reason += _score_sentence(score, review, weak)
        return Decision(
            verdict=VERDICT_NO_GO,
            score=score,
            rule=1,
            reason=reason,
            review_threshold=review,
            go_threshold=go,
            weak_metrics=weak,
            suggested_fixes=_fixes(weak),
            hard_gate_failures=tuple(gate_failures),
        )

    if summary.valid_items == 0:
        reason = (
            "The run produced no valid items, so there is nothing to score. "
            "Every case failed before the app returned an answer; check the connector "
            "and the failed cases, then run again."
        )
        return Decision(
            verdict=VERDICT_NO_GO,
            score=score,
            rule=1,
            reason=reason,
            review_threshold=review,
            go_threshold=go,
            weak_metrics=weak,
            suggested_fixes=_fixes(weak),
        )

    if score is None:
        reason = (
            "No metric could be measured, so the run cannot be scored. "
            "Instrument the app's answer and context, or check the connector settings."
        )
        return Decision(
            verdict=VERDICT_NO_GO,
            score=None,
            rule=1,
            reason=reason,
            review_threshold=review,
            go_threshold=go,
        )

    # Rule 2: below the review threshold is a NO-GO.
    if score < review:
        reason = (
            f"Weighted score {_format_score(score)} is below the REVIEW threshold "
            f"{_format_score(review)}. {_weak_sentence(weak)}"
        )
        return Decision(
            verdict=VERDICT_NO_GO,
            score=score,
            rule=2,
            reason=reason,
            review_threshold=review,
            go_threshold=go,
            weak_metrics=weak,
            suggested_fixes=_fixes(weak),
        )

    # Rule 3: the judge could not be trusted, so a human should look.
    if _judge_needs_review(summary.judge):
        reason = (
            f"{_judge_sentence(summary.judge)} Weighted score "
            f"{_format_score(score)} is above the REVIEW threshold "
            f"{_format_score(review)}, but a human should confirm."
        )
        return Decision(
            verdict=VERDICT_REVIEW,
            score=score,
            rule=3,
            reason=reason,
            review_threshold=review,
            go_threshold=go,
            weak_metrics=weak,
            suggested_fixes=_fixes(weak),
        )

    # Rule 4: between the two thresholds is a REVIEW.
    if score < go:
        reason = (
            f"Weighted score {_format_score(score)} is between the REVIEW threshold "
            f"{_format_score(review)} and the GO threshold {_format_score(go)}. "
            f"{_weak_sentence(weak)}"
        )
        return Decision(
            verdict=VERDICT_REVIEW,
            score=score,
            rule=4,
            reason=reason,
            review_threshold=review,
            go_threshold=go,
            weak_metrics=weak,
            suggested_fixes=_fixes(weak),
        )

    # Rule 5: everything cleared the bar.
    reason = (
        f"Weighted score {_format_score(score)} is at or above the GO threshold "
        f"{_format_score(go)} and no hard gate failed."
    )
    if weak:
        reason += f" {_weak_sentence(weak)}"
    return Decision(
        verdict=VERDICT_GO,
        score=score,
        rule=5,
        reason=reason,
        review_threshold=review,
        go_threshold=go,
        weak_metrics=weak,
        suggested_fixes=_fixes(weak),
    )


def _hard_gate_failures(results: Mapping[str, MetricResult], profile: CriteriaProfile) -> list[str]:
    failures: list[str] = []
    for criterion in profile.criteria:
        if not criterion.hard_gate:
            continue
        result = results.get(criterion.metric)
        if result is None or not result.instrumented:
            continue
        if not result.passed:
            failures.append(criterion.metric)
    return failures


def _weak_metrics(
    results: Mapping[str, MetricResult], profile: CriteriaProfile
) -> tuple[tuple[str, float], ...]:
    scored = [
        (criterion.metric, results[criterion.metric].score)
        for criterion in profile.criteria
        if criterion.metric in results
        and results[criterion.metric].instrumented
        # A perfect metric is not worth listing as a weakness.
        and results[criterion.metric].score < 0.999
    ]
    scored.sort(key=lambda pair: pair[1])
    return tuple(scored[:MAX_WEAK_METRICS])


def _fixes(weak: Sequence[tuple[str, float]]) -> tuple[str, ...]:
    fixes: list[str] = []
    for name, _score in weak:
        fix = SUGGESTED_FIXES.get(name)
        if fix and fix not in fixes:
            fixes.append(fix)
    return tuple(fixes)


def _judge_needs_review(judge: JudgeStatus) -> bool:
    return (
        judge.unavailable_items > 0
        or judge.low_confidence_items > 0
        or judge.disagreements > judge.tolerance
    )


def _judge_sentence(judge: JudgeStatus) -> str:
    parts: list[str] = []
    if judge.unavailable_items:
        parts.append(f"the judge was unavailable for {judge.unavailable_items} item(s)")
    if judge.low_confidence_items:
        parts.append(f"the judge was not confident about {judge.low_confidence_items} item(s)")
    if judge.disagreements > judge.tolerance:
        parts.append(
            f"judge and human labels disagree on {judge.disagreements} item(s) "
            f"(tolerance {judge.tolerance})"
        )
    return "; ".join(parts).capitalize() + "."


def _score_sentence(score: float | None, review: float, weak: Sequence[tuple[str, float]]) -> str:
    if score is None:
        return "No metric could be measured."
    return (
        f"Weighted score {_format_score(score)} against the REVIEW threshold "
        f"{_format_score(review)}. {_weak_sentence(weak)}"
    )


def _weak_sentence(weak: Sequence[tuple[str, float]]) -> str:
    if not weak:
        return "No metric was weak."
    listed = ", ".join(f"{name} {_format_score(value)}" for name, value in weak)
    return f"Weakest metrics: {listed}."


def _threshold(profile: CriteriaProfile, metric: str) -> float:
    for criterion in profile.criteria:
        if criterion.metric == metric:
            return criterion.threshold
    return 0.0


def _format_score(value: float) -> str:
    return f"{value:.2f}"
