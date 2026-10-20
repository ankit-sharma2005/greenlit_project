from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from app.phase4_schemas import MetricScoreOut
from app.phase5_schemas import (
    CategoryResult,
    ReadinessIssue,
    ReadinessReport,
    RunVerdict,
    VerdictCriteria,
)
from app.services.metrics import canonical_metric_name


@dataclass(frozen=True)
class VerdictItem:
    id: str
    position: int
    status: str
    category: str
    scores: Sequence[MetricScoreOut]
    error: str | None = None


def evaluate_verdict(
    criteria: VerdictCriteria,
    items: Sequence[VerdictItem],
    *,
    run_status: str,
) -> RunVerdict:
    readiness_issues: list[ReadinessIssue] = []
    category_metric_values: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    hard_gate_failures: list[str] = []
    failed_items = [item for item in items if item.status == "failed"]
    judge_errors: list[tuple[VerdictItem, MetricScoreOut]] = []

    for item in items:
        if item.status != "completed":
            if item.status == "failed":
                readiness_issues.append(
                    ReadinessIssue(
                        component="application execution",
                        message=item.error
                        or f"Item #{item.position} failed to execute.",
                        run_item_id=item.id,
                    )
                )
            elif item.status in {"pending", "running"}:
                readiness_issues.append(
                    ReadinessIssue(
                        component="run completion",
                        message=f"Item #{item.position} is {item.status}.",
                        run_item_id=item.id,
                    )
                )

        for score in item.scores:
            if score.status != "scored" or score.score is None:
                if score.method == "llm_judge" and score.status == "error":
                    judge_errors.append((item, score))
                if score.status in {"error", "not_instrumented", "not_configured"}:
                    readiness_issues.append(
                        ReadinessIssue(
                            component=score.name,
                            message=score.reason,
                            run_item_id=item.id,
                        )
                    )
                continue

            metric_key = (
                f"{score.name}:{score.judge_role}"
                if score.judge_role is not None
                else score.name
            )
            category_metric_values[score.category][metric_key].append(score.score)
            gate_metric_name = canonical_metric_name(
                score.name.split(":", maxsplit=1)[0]
            )
            gate_threshold = criteria.hard_gates.get(gate_metric_name)
            if gate_threshold is not None and score.score < gate_threshold:
                hard_gate_failures.append(
                    f"Hard gate '{gate_metric_name}' failed on item "
                    f"#{item.position}: "
                    f"score {score.score:.2f} is below required {gate_threshold:.2f}."
                )

    category_results: list[CategoryResult] = []
    for category in sorted(category_metric_values):
        per_metric_means = [
            sum(values) / len(values)
            for values in category_metric_values[category].values()
        ]
        category_results.append(
            CategoryResult(
                category=category,
                score=sum(per_metric_means) / len(per_metric_means),
                weight=criteria.category_weights.get(category, 1.0),
                metric_count=len(per_metric_means),
            )
        )

    weighted_total = sum(
        category.score * category.weight for category in category_results
    )
    total_weight = sum(category.weight for category in category_results)
    overall_score = weighted_total / total_weight if total_weight else None

    verdict: Literal["GO", "REVIEW", "NO_GO"]
    if hard_gate_failures:
        verdict = "NO_GO"
        reasons = hard_gate_failures
        summary = "A configured hard gate failed."
    elif run_status in {"failed", "cancelled"} or failed_items:
        verdict = "NO_GO"
        reasons = (
            [f"Run status is '{run_status}'."]
            if run_status in {"failed", "cancelled"}
            else [f"Item #{item.position} failed to execute." for item in failed_items]
        )
        summary = "The evaluation did not complete successfully."
    elif run_status not in {"completed", "failed", "cancelled"}:
        verdict = "REVIEW"
        reasons = ["The evaluation run is not complete."]
        summary = "The run must finish before a final verdict can be issued."
    elif judge_errors:
        verdict = "REVIEW"
        reasons = [
            f"Judge metric '{score.name}' failed on item #{item.position}: "
            f"{score.reason}"
            for item, score in judge_errors
        ]
        summary = "At least one configured judge did not produce a score."
    elif overall_score is None:
        verdict = "REVIEW"
        reasons = ["No configured metrics produced a score."]
        summary = "There is not enough scored data to issue a final verdict."
    elif overall_score >= criteria.go_threshold:
        verdict = "GO"
        reasons = [
            f"Weighted score {overall_score:.2f} >= GO threshold "
            f"{criteria.go_threshold:.2f}."
        ]
        summary = "The weighted score meets the GO threshold."
    elif overall_score >= criteria.review_threshold:
        verdict = "REVIEW"
        reasons = [
            f"Weighted score {overall_score:.2f} is between REVIEW threshold "
            f"{criteria.review_threshold:.2f} and GO threshold "
            f"{criteria.go_threshold:.2f}."
        ]
        summary = "The weighted score requires review."
    else:
        verdict = "NO_GO"
        reasons = [
            f"Weighted score {overall_score:.2f} < REVIEW threshold "
            f"{criteria.review_threshold:.2f}."
        ]
        summary = "The weighted score is below the REVIEW threshold."

    return RunVerdict(
        verdict=verdict,
        score=overall_score,
        summary=summary,
        reasons=reasons,
        categories=category_results,
        readiness=ReadinessReport(
            status="needs_attention" if readiness_issues else "ready",
            issues=readiness_issues,
        ),
    )


def readiness_issues_for_trace(trace: Mapping[str, object]) -> list[ReadinessIssue]:
    steps = trace.get("steps")
    available_steps = steps if isinstance(steps, dict) else {}
    usage = trace.get("usage")
    available_usage = usage if isinstance(usage, dict) else {}
    required_fields: tuple[tuple[str, object], ...] = (
        ("model_used", trace.get("model_used")),
        ("usage.tokens_in", available_usage.get("tokens_in")),
        ("usage.tokens_out", available_usage.get("tokens_out")),
        ("steps.retrieved_chunks", available_steps.get("retrieved_chunks")),
        ("steps.tool_calls", available_steps.get("tool_calls")),
    )
    return [
        ReadinessIssue(
            component=field_name,
            message=f"Trace field '{field_name}' is missing.",
        )
        for field_name, value in required_fields
        if value is None
    ]


def criteria_snapshot(value: Mapping[str, object] | None) -> VerdictCriteria:
    return VerdictCriteria.model_validate(dict(value or {}))
