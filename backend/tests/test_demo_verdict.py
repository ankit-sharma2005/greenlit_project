from __future__ import annotations

from pathlib import Path
from typing import cast

from app.services.demo_verdict import evaluate_demo_output
from app.services.metrics import _answer_similarity_score

ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = ROOT / "greenlit_demo"


def test_demo_verdicts_are_real_and_different() -> None:
    good = evaluate_demo_output(
        DEMO_DIR / "golden_dataset.csv",
        DEMO_DIR / "outputs_good.csv",
    )
    broken = evaluate_demo_output(
        DEMO_DIR / "golden_dataset.csv",
        DEMO_DIR / "outputs_broken.csv",
    )

    assert good["verdict"] == "GO"
    assert broken["verdict"] == "NO_GO"
    assert good["score"] is not None
    assert broken["score"] is not None
    good_score = float(cast(float, good["score"]))
    broken_score = float(cast(float, broken["score"]))
    assert good_score > broken_score

    good_metrics_raw = good["metrics"]
    broken_metrics_raw = broken["metrics"]
    assert isinstance(good_metrics_raw, list)
    assert isinstance(broken_metrics_raw, list)
    assert isinstance(good_metrics_raw[0], dict)
    assert isinstance(broken_metrics_raw[0], dict)
    good_metrics = good_metrics_raw[0]["metrics"]
    broken_metrics = broken_metrics_raw[0]["metrics"]
    assert isinstance(good_metrics, list)
    assert isinstance(broken_metrics, list)
    assert any(
        metric["name"] == "answer_match" and metric["score"] == 1.0
        for metric in good_metrics
    )
    assert any(
        metric["name"] == "answer_match" and metric["score"] < 1.0
        for metric in broken_metrics
    )
    assert any(
        metric["name"] == "retrieval_context_recall" and metric["score"] < 0.8
        for metric in broken_metrics
    )
    assert (
        _answer_similarity_score(
            "GreenLit evaluates LLM applications before launch.",
            "GreenLit evaluates LLM applications before launch.",
        )
        == 1.0
    )
    assert broken["summary"] == "The weighted score is below the REVIEW threshold."
    reasons = broken["reasons"]
    assert isinstance(reasons, list)
    assert reasons == ["Weighted score 0.59 < REVIEW threshold 0.60."]


def test_answer_match_accepts_paraphrase_and_rejects_unrelated_answer() -> None:
    paraphrase_score = _answer_similarity_score(
        "GreenLit evaluates LLM applications before launch.",
        "GreenLit assesses LLM products before release.",
    )
    unrelated_score = _answer_similarity_score(
        "GreenLit evaluates LLM applications before launch.",
        "It is raining in Seattle and the stock market is volatile.",
    )

    assert paraphrase_score >= 0.6
    assert unrelated_score < 0.4
