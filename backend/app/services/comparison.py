from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict
from uuid import UUID

from app.phase4_schemas import MetricScoreOut
from app.phase6_schemas import (
    MetricComparison,
    RegressionFailure,
    RegressionReportOut,
    RunComparisonOut,
)
from app.services.statistics import (
    holm_adjust,
    mcnemar_exact_p_value,
    paired_bootstrap_interval,
    paired_permutation_p_value,
)

ALPHA = 0.05
ITEM_PASS_THRESHOLD = 0.5
QUALITY_REGRESSION_TOLERANCE = 0.02


class _RawMetric(TypedDict):
    metric: str
    category: str
    baseline_mean: float
    candidate_mean: float
    delta: float
    confidence_interval: tuple[float, float]
    paired_permutation_p_value: float
    mcnemar_p_value: float
    sample_size: int
    wins: int
    ties: int
    losses: int


@dataclass(frozen=True)
class ComparisonItem:
    id: UUID
    position: int
    regression_critical: bool
    status: str
    scores: Sequence[MetricScoreOut]


def compare_runs(
    baseline_run_id: UUID,
    candidate_run_id: UUID,
    baseline_items: Sequence[ComparisonItem],
    candidate_items: Sequence[ComparisonItem],
) -> RunComparisonOut:
    baseline_by_id = {item.id: item for item in baseline_items}
    candidate_by_id = {item.id: item for item in candidate_items}
    common_ids = sorted(baseline_by_id.keys() & candidate_by_id.keys(), key=str)
    warnings: list[str] = []
    if not common_ids:
        return RunComparisonOut(
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            outcome="insufficient_data",
            confidence_level=0.95,
            metrics=[],
            warnings=["Runs have no paired dataset items."],
        )

    if len(common_ids) < 10:
        warnings.append(
            f"Small sample: only {len(common_ids)} dataset items are paired."
        )

    baseline_values = _score_values(baseline_by_id, common_ids)
    candidate_values = _score_values(candidate_by_id, common_ids)
    raw_metrics: list[_RawMetric] = []
    for metric in sorted(baseline_values.keys() & candidate_values.keys()):
        paired_ids = sorted(
            baseline_values[metric].keys() & candidate_values[metric].keys(),
            key=str,
        )
        if not paired_ids:
            continue
        before = [baseline_values[metric][item_id][0] for item_id in paired_ids]
        after = [candidate_values[metric][item_id][0] for item_id in paired_ids]
        category = baseline_values[metric][paired_ids[0]][1]
        delta = sum(
            after_value - before_value
            for before_value, after_value in zip(before, after, strict=True)
        ) / len(before)
        raw_metrics.append(
            {
                "metric": metric,
                "category": category,
                "baseline_mean": float(sum(before) / len(before)),
                "candidate_mean": float(sum(after) / len(after)),
                "delta": delta,
                "confidence_interval": paired_bootstrap_interval(
                    before, after, seed=_stable_seed(metric)
                ),
                "paired_permutation_p_value": paired_permutation_p_value(
                    before, after, seed=_stable_seed(metric)
                ),
                "mcnemar_p_value": mcnemar_exact_p_value(
                    [value >= ITEM_PASS_THRESHOLD for value in before],
                    [value >= ITEM_PASS_THRESHOLD for value in after],
                ),
                "sample_size": len(before),
                "wins": sum(new > old for old, new in zip(before, after, strict=True)),
                "ties": sum(new == old for old, new in zip(before, after, strict=True)),
                "losses": sum(
                    new < old for old, new in zip(before, after, strict=True)
                ),
            }
        )

    if not raw_metrics:
        warnings.append("No shared scored metrics were found for paired items.")
        outcome: Literal[
            "significant_difference",
            "no_significant_difference",
            "insufficient_data",
        ] = "insufficient_data"
        metrics: list[MetricComparison] = []
    else:
        adjusted = holm_adjust(
            [metric["paired_permutation_p_value"] for metric in raw_metrics]
        )
        metrics = []
        for values, adjusted_p in zip(raw_metrics, adjusted, strict=True):
            delta = values["delta"]
            significant = adjusted_p < ALPHA
            classification: Literal[
                "improved", "no_significant_change", "regressed"
            ] = (
                "improved"
                if significant and delta > 0
                else "regressed"
                if significant and delta < 0
                else "no_significant_change"
            )
            metrics.append(
                MetricComparison(
                    metric=values["metric"],
                    category=values["category"],
                    baseline_mean=values["baseline_mean"],
                    candidate_mean=values["candidate_mean"],
                    delta=delta,
                    confidence_interval=values["confidence_interval"],
                    paired_permutation_p_value=values["paired_permutation_p_value"],
                    holm_adjusted_p_value=adjusted_p,
                    mcnemar_p_value=values["mcnemar_p_value"],
                    sample_size=values["sample_size"],
                    wins=values["wins"],
                    ties=values["ties"],
                    losses=values["losses"],
                    significant=significant,
                    classification=classification,
                )
            )
        outcome = (
            "significant_difference"
            if any(metric.significant for metric in metrics)
            else "no_significant_difference"
        )

    return RunComparisonOut(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        outcome=outcome,
        confidence_level=0.95,
        metrics=metrics,
        warnings=warnings,
    )


def regression_report(
    comparison: RunComparisonOut,
    baseline_items: Sequence[ComparisonItem],
    candidate_items: Sequence[ComparisonItem],
) -> RegressionReportOut:
    baseline_by_id = {item.id: item for item in baseline_items}
    candidate_by_id = {item.id: item for item in candidate_items}
    failures: list[RegressionFailure] = []

    for item_id in sorted(baseline_by_id.keys() & candidate_by_id.keys(), key=str):
        before = baseline_by_id[item_id]
        after = candidate_by_id[item_id]
        before_scores = {
            score.name: score.score
            for score in before.scores
            if score.status == "scored" and score.score is not None
        }
        after_scores = {
            score.name: score.score
            for score in after.scores
            if score.status == "scored" and score.score is not None
        }
        for metric in sorted(before_scores.keys() & after_scores.keys()):
            baseline_score = before_scores[metric]
            candidate_score = after_scores[metric]
            if (
                baseline_score >= ITEM_PASS_THRESHOLD
                and candidate_score < ITEM_PASS_THRESHOLD
            ):
                failures.append(
                    RegressionFailure(
                        dataset_item_id=item_id,
                        position=after.position,
                        metric=metric,
                        baseline_score=baseline_score,
                        candidate_score=candidate_score,
                        regression_critical=after.regression_critical,
                    )
                )
        if before.status != "failed" and after.status == "failed":
            failures.append(
                RegressionFailure(
                    dataset_item_id=item_id,
                    position=after.position,
                    metric="application_execution",
                    baseline_score=1.0,
                    candidate_score=0.0,
                    regression_critical=after.regression_critical,
                )
            )

    critical_failures = [failure for failure in failures if failure.regression_critical]
    significant_quality_drops = [
        metric
        for metric in comparison.metrics
        if metric.category == "quality"
        and metric.delta < -QUALITY_REGRESSION_TOLERANCE
        and metric.significant
    ]
    status: Literal["PASS", "WARN", "BLOCK"]
    if critical_failures:
        status = "BLOCK"
        reasons = [
            f"Regression-critical item #{failure.position} newly failed "
            f"'{failure.metric}'."
            for failure in critical_failures
        ]
    elif significant_quality_drops:
        status = "BLOCK"
        reasons = [
            f"Quality metric '{metric.metric}' dropped by "
            f"{abs(metric.delta):.3f}, exceeding the 0.020 tolerance with "
            "statistical significance."
            for metric in significant_quality_drops
        ]
    elif failures:
        status = "WARN"
        reasons = [f"{len(failures)} previously passing item/metric pair(s) now fail."]
    elif comparison.outcome == "insufficient_data":
        status = "WARN"
        reasons = ["Regression comparison has insufficient paired score data."]
    else:
        status = "PASS"
        reasons = ["No blocking regression was detected."]

    return RegressionReportOut(
        baseline_run_id=comparison.baseline_run_id,
        candidate_run_id=comparison.candidate_run_id,
        status=status,
        reasons=reasons,
        new_failures=failures,
        comparison=comparison,
    )


def _score_values(
    items: dict[UUID, ComparisonItem], item_ids: Sequence[UUID]
) -> dict[str, dict[UUID, tuple[float, str]]]:
    values: dict[str, dict[UUID, tuple[float, str]]] = {}
    for item_id in item_ids:
        for score in items[item_id].scores:
            if score.status == "scored" and score.score is not None:
                values.setdefault(score.name, {})[item_id] = (
                    score.score,
                    score.category,
                )
    return values


def _stable_seed(value: str) -> int:
    return sum((index + 1) * ord(character) for index, character in enumerate(value))
