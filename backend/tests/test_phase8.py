from __future__ import annotations

import pytest

from app.phase8_schemas import BlindComparisonOut, CalibrationSummaryOut
from app.services.human_review import (
    ReviewItem,
    blind_ab_compare,
    calibration_summary,
    final_report_rescore,
    queue_review_items,
    validate_override,
)


def test_review_queue_auto_queues_risky_items() -> None:
    items = [
        ReviewItem(
            item_id="low-conf",
            score=0.72,
            confidence=0.4,
            threshold=0.75,
            gate_failed=False,
            judge_votes=(0.6, 0.9),
            version="v1",
        ),
        ReviewItem(
            item_id="high-conf",
            score=0.9,
            confidence=0.95,
            threshold=0.75,
            gate_failed=False,
            judge_votes=(0.88, 0.9),
            version="v2",
        ),
        ReviewItem(
            item_id="gate-fail",
            score=0.63,
            confidence=0.8,
            threshold=0.75,
            gate_failed=True,
            judge_votes=(0.7, 0.6),
            version="v3",
        ),
    ]

    results = queue_review_items(items)

    assert [entry.item_id for entry in results] == ["low-conf", "gate-fail"]
    assert all(entry.status == "queued" for entry in results)
    assert "low_confidence" in results[0].reasons


def test_calibration_summary_reports_kappa_alpha_and_confusion_data() -> None:
    summary = calibration_summary(
        actual=["A", "A", "B", "B"],
        predicted=["A", "B", "B", "B"],
    )

    assert isinstance(summary, CalibrationSummaryOut)
    assert summary.n_items == 4
    assert -1.0 <= summary.cohens_kappa <= 1.0
    assert -1.0 <= summary.krippendorffs_alpha <= 1.0
    assert -1.0 <= summary.spearman_rho <= 1.0
    assert summary.confusion_matrix["A"]["A"] >= 0
    assert "A" in summary.confusion_matrix


def test_blind_ab_compare_hides_labels_and_reports_winner() -> None:
    result = blind_ab_compare(0.7, 0.9, left_label="Variant A", right_label="Variant B")

    assert isinstance(result, BlindComparisonOut)
    assert result.blinded is True
    assert result.left_label == "Variant A"
    assert result.right_label == "Variant B"
    assert result.delta == pytest.approx(0.2)
    assert result.winner == "right"


def test_override_requires_justification_and_tracks_audit_flag() -> None:
    result = validate_override("Needed for policy safety.", audit_logged=True)

    assert result.approved is True
    assert result.requires_justification is True
    assert result.justification == "Needed for policy safety."
    assert result.audit_logged is True

    blocked = validate_override(" ", audit_logged=False)
    assert blocked.approved is False
    assert blocked.justification == ""


def test_final_report_reruns_score_summary_without_live_calls() -> None:
    report = final_report_rescore(
        [{"quality": 0.92, "latency": 0.8}, {"quality": 0.71, "latency": 0.86}],
        threshold=0.75,
    )

    assert report.status == "WARN"
    assert report.rerun_without_live_calls is True
    assert report.item_count == 2
    assert report.metric_means["quality"] == pytest.approx(0.815)
    assert report.warnings
