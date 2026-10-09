from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import isnan
from typing import Any, Literal

from app.phase8_schemas import (
    BlindComparisonOut,
    CalibrationSummaryOut,
    FinalReportOut,
    OverrideDecisionOut,
    ReviewQueueEntry,
)


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    score: float = 0.0
    confidence: float = 1.0
    threshold: float = 0.75
    gate_failed: bool = False
    judge_votes: Sequence[float] = field(default_factory=tuple)
    version: str = "unknown"
    justification: str = ""


def _as_review_item(item: ReviewItem | dict[str, Any]) -> ReviewItem:
    if isinstance(item, ReviewItem):
        return item
    if not isinstance(item, dict):
        raise TypeError("Review items must be ReviewItem instances or dictionaries")
    return ReviewItem(
        item_id=str(item.get("item_id") or item.get("id") or "item"),
        score=float(item.get("score", 0.0)),
        confidence=float(item.get("confidence", 1.0)),
        threshold=float(item.get("threshold", 0.75)),
        gate_failed=bool(item.get("gate_failed", False)),
        judge_votes=tuple(float(v) for v in item.get("judge_votes", ())),
        version=str(item.get("version", "unknown")),
        justification=str(item.get("justification", "")),
    )


def queue_review_items(
    items: Sequence[ReviewItem | dict[str, Any]], *, threshold: float = 0.75
) -> list[ReviewQueueEntry]:
    queued: list[ReviewQueueEntry] = []
    for item in items:
        review_item = _as_review_item(item)
        reasons: list[str] = []
        if review_item.confidence < 0.6:
            reasons.append("low_confidence")
        if review_item.gate_failed:
            reasons.append("gate_failed")
        if len(review_item.judge_votes) >= 2:
            spread = max(review_item.judge_votes) - min(review_item.judge_votes)
            if spread > 0.25:
                reasons.append("disagreeing")
        if abs(review_item.score - review_item.threshold) <= 0.05:
            reasons.append("near_threshold")
        if not reasons:
            continue
        queued.append(
            ReviewQueueEntry(
                item_id=review_item.item_id,
                score=review_item.score,
                confidence=review_item.confidence,
                threshold=threshold,
                reasons=reasons,
                version=review_item.version,
                status="queued",
            )
        )
    return queued


build_review_queue = queue_review_items
auto_queue_review_items = queue_review_items


def _safe_pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        return 0.0
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    x_dev = [value - x_mean for value in xs]
    y_dev = [value - y_mean for value in ys]
    numerator = sum(
        left * right for left, right in zip(x_dev, y_dev, strict=True)
    )
    x_norm = sum(value * value for value in x_dev) ** 0.5
    y_norm = sum(value * value for value in y_dev) ** 0.5
    if x_norm == 0 or y_norm == 0:
        return 0.0
    return float(numerator / (x_norm * y_norm))


def calibration_summary(
    actual: Sequence[float | int | str],
    predicted: Sequence[float | int | str],
) -> CalibrationSummaryOut:
    if len(actual) != len(predicted):
        raise ValueError("actual and predicted sequences must be the same length")
    if not actual:
        return CalibrationSummaryOut(
            n_items=0,
            cohens_kappa=0.0,
            krippendorffs_alpha=0.0,
            spearman_rho=0.0,
            confusion_matrix={},
            notes=["No calibration data available."],
        )

    labels = sorted({str(value) for value in set(actual) | set(predicted)})
    matrix: dict[str, dict[str, int]] = {
        label: {other: 0 for other in labels} for label in labels
    }
    for truth, estimate in zip(actual, predicted, strict=True):
        truth_label = str(truth)
        estimate_label = str(estimate)
        matrix[truth_label][estimate_label] += 1

    total = len(actual)
    observed = sum(matrix[label][label] for label in labels) / total
    expected = 0.0
    for label in labels:
        truth_total = sum(matrix[label][other] for other in labels)
        pred_total = sum(matrix[other][label] for other in labels)
        expected += (truth_total / total) * (pred_total / total)
    cohens_kappa = 0.0 if expected >= 1 else (observed - expected) / (1 - expected)
    if expected >= 1:
        cohens_kappa = 1.0 if observed == 1 else 0.0

    disagreement = 0
    expected_disagreement = 0
    for truth_label in labels:
        for estimate_label in labels:
            if truth_label != estimate_label:
                disagreement += matrix[truth_label][estimate_label]
    for label in labels:
        truth_total = sum(matrix[label][other] for other in labels)
        pred_total = sum(matrix[other][label] for other in labels)
        expected_disagreement += (truth_total / total) * (pred_total / total)
    alpha = 0.0
    if expected_disagreement > 0:
        alpha = 1.0 - (disagreement / total) / expected_disagreement

    score_map = {label: index for index, label in enumerate(labels)}
    rho = _safe_pearson(
        [score_map[str(value)] for value in actual],
        [score_map[str(value)] for value in predicted],
    )
    note = (
        "Agreement computed with a deterministic nominal formulation suitable "
        "for review calibration."
    )
    return CalibrationSummaryOut(
        n_items=total,
        cohens_kappa=max(-1.0, min(1.0, cohens_kappa)),
        krippendorffs_alpha=max(-1.0, min(1.0, alpha)),
        spearman_rho=max(-1.0, min(1.0, rho)),
        confusion_matrix=matrix,
        notes=[note],
    )


summarize_calibration = calibration_summary


def blind_ab_compare(
    left_score: float,
    right_score: float,
    *,
    left_label: str = "Variant A",
    right_label: str = "Variant B",
) -> BlindComparisonOut:
    delta = right_score - left_score
    if abs(delta) < 1e-9:
        winner: Literal["left", "right", "tie"] = "tie"
    elif delta > 0:
        winner = "right"
    else:
        winner = "left"
    return BlindComparisonOut(
        left_label=left_label,
        right_label=right_label,
        blinded=True,
        delta=delta,
        winner=winner,
    )


validate_blind_comparison = blind_ab_compare


def validate_override(
    justification: str,
    *,
    require_justification: bool = True,
    audit_logged: bool = False,
) -> OverrideDecisionOut:
    approved = bool(justification.strip()) if require_justification else True
    return OverrideDecisionOut(
        approved=approved,
        requires_justification=require_justification,
        justification=justification.strip(),
        audit_logged=audit_logged,
    )


apply_override = validate_override
audit_override = validate_override


def final_report_rescore(
    stored_traces: Sequence[dict[str, float]],
    *,
    threshold: float = 0.75,
) -> FinalReportOut:
    if not stored_traces:
        return FinalReportOut(
            status="READY",
            item_count=0,
            metric_means={},
            warnings=["No stored traces were provided; final report is ready for review."],
        )

    metrics: dict[str, list[float]] = {}
    for trace in stored_traces:
        for metric, value in trace.items():
            if isinstance(value, int | float) and not isnan(float(value)):
                metrics.setdefault(metric, []).append(float(value))

    metric_means = {
        key: sum(values) / len(values) if values else 0.0 for key, values in metrics.items()
    }
    failing = {key: value for key, value in metric_means.items() if value < threshold}
    warnings: list[str] = []
    if failing:
        warnings.append(
            "One or more metrics fell below the threshold and should be reviewed manually."
        )
    elif any(value < 0.85 for value in metric_means.values()):
        warnings.append(
            "One or more metrics are below the preferred review threshold and should be inspected."
        )

    if failing:
        status: Literal["PASS", "WARN", "BLOCK", "READY"] = "BLOCK"
    elif warnings:
        status = "WARN"
    elif metric_means:
        status = "PASS"
    else:
        status = "READY"

    return FinalReportOut(
        status=status,
        item_count=len(stored_traces),
        metric_means=metric_means,
        warnings=warnings,
        rerun_without_live_calls=True,
    )


final_report = final_report_rescore
re_score_final_report = final_report_rescore
