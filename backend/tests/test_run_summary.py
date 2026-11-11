"""The run in plain words (L1): exact wording for every kind of finished run.

Every fixture here is a run the product can actually produce: a GO, a REVIEW
between the thresholds, a NO-GO from a hard gate, a NO-GO from a low score, a
REVIEW because the judge was unsure, a run whose context was never measured, a
run stopped by a limit, and a run with nothing in it. The text is templates, so
each test asserts the sentence a reader gets, word for word — and that a metric
nobody measured is named rather than printed as a 0.00.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.report import _summary_html
from app.services.run_summary import build_run_summary

GO_THRESHOLD = 0.80
REVIEW_THRESHOLD = 0.60
UNMEASURED_SAFETY = "Safety was not measured on this run, so this summary claims nothing about it."


def metric(
    name: str,
    score: float,
    *,
    instrumented: bool = True,
    passed: bool | None = None,
    threshold: float = 0.60,
    hard_gate: bool = False,
    explanation: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "score": score,
        "passed": score >= threshold if passed is None else passed,
        "instrumented": instrumented,
        "threshold": threshold,
        "hard_gate": hard_gate,
        "explanation": explanation,
        "details": details or {},
    }


def decision(
    rule: int,
    *,
    gates: list[str] | None = None,
    weak: list[tuple[str, float]] | None = None,
    fixes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "rule": rule,
        "review_threshold": REVIEW_THRESHOLD,
        "go_threshold": GO_THRESHOLD,
        "hard_gate_failures": gates or [],
        "weak_metrics": [{"metric": name, "score": score} for name, score in (weak or [])],
        "suggested_fixes": fixes or [],
    }


def summary(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "verdict": "GO",
        "score": 0.86,
        "decision": decision(5),
        "metrics": [metric("answer_match", 0.9)],
        "judge": None,
        "cases_total": 10,
        "state": "COMPLETED",
    }
    base.update(overrides)
    return build_run_summary(**base)


def test_a_go_says_the_score_and_the_go_threshold() -> None:
    result = summary()

    assert result["headline"] == (
        "GreenLit says GO: the weighted score was 0.86, at or above the 0.80 go threshold."
    )
    assert result["reasons"] == []
    assert result["weakest_sentence"] == "No measured metric was weak."
    assert result["not_measured"] == []
    assert result["not_measured_sentence"] == ""
    assert result["safety_sentence"] == UNMEASURED_SAFETY
    assert result["next_steps"] == ["Nothing to fix: every gate passed and no metric was weak."]


def test_a_review_between_the_thresholds_names_both_of_them() -> None:
    fix = (
        "answers do not contain the expected facts: check the prompt, the model and the"
        " retrieval step"
    )
    result = summary(
        verdict="REVIEW",
        score=0.72,
        decision=decision(4, weak=[("answer_match", 0.62)], fixes=[fix]),
        metrics=[metric("answer_match", 0.62)],
    )

    assert result["headline"] == (
        "GreenLit says REVIEW: the weighted score was 0.72, between the 0.60 review and"
        " 0.80 go thresholds."
    )
    assert result["weakest_sentence"] == "Weakest measured metrics: answer match 0.62."
    assert result["next_steps"] == [fix]


def test_a_no_go_from_a_hard_gate_names_the_gate_and_its_reason() -> None:
    result = summary(
        verdict="NO_GO",
        score=0.91,
        decision=decision(1, gates=["output_nonempty"]),
        metrics=[
            metric(
                "output_nonempty",
                0.5,
                threshold=1.0,
                hard_gate=True,
                passed=False,
                explanation="some answers were empty",
            )
        ],
    )

    assert result["headline"] == (
        "GreenLit says NO-GO: the hard gate output nonempty failed, so a weighted score of"
        " 0.91 could not save it."
    )
    assert result["reasons"] == [
        "The hard gate output nonempty failed: it scored 0.50 (needs 1.00)."
        " Some answers were empty."
    ]
    assert result["next_steps"] == [
        "some answers were empty: check the app's error handling and prompt"
    ]


def test_a_no_go_from_a_low_score_says_the_review_threshold() -> None:
    result = summary(
        verdict="NO_GO",
        score=0.54,
        decision=decision(2, weak=[("answer_match", 0.50)]),
        metrics=[metric("answer_match", 0.50)],
    )

    assert result["headline"] == (
        "GreenLit says NO-GO: the weighted score was 0.54, below the 0.60 review threshold."
    )
    assert result["weakest"] == [{"metric": "answer_match", "label": "answer match", "score": 0.5}]


def test_a_judge_that_was_unsure_makes_a_review_and_says_so() -> None:
    result = summary(
        verdict="REVIEW",
        score=0.88,
        decision=decision(3),
        judge={"unavailable_items": 0, "low_confidence_items": 2},
    )

    assert result["headline"] == (
        "GreenLit says REVIEW: the judge could not be trusted, so the score of 0.88 needs a"
        " person to look at it."
    )
    assert result["reasons"] == ["The judge was unsure on 2 case(s), so a person should read them."]
    assert result["next_steps"] == [
        "Read the cases the judge was unsure about before trusting the verdict."
    ]


def test_an_unmeasured_metric_is_named_and_never_scored_as_zero() -> None:
    result = summary(
        metrics=[
            metric("answer_match", 0.9),
            metric(
                "retrieval_context_recall",
                0.0,
                instrumented=False,
                passed=False,
                explanation="no retrieved context was reported",
            ),
        ],
    )

    assert result["not_measured"] == ["retrieval context recall"]
    assert result["not_measured_sentence"] == (
        "Not measured on this run: retrieval context recall. It is left out of the weighted"
        " score and not counted as zero."
    )
    # No number is ever attached to the metric that was not measured.
    assert (
        re.search(r"retrieval context recall[^.]*\d\.\d\d", result["not_measured_sentence"]) is None
    )
    assert "0.00" not in result["not_measured_sentence"]
    assert result["weakest"] == []


def test_a_run_stopped_by_a_limit_says_what_to_change() -> None:
    result = summary(
        verdict="REVIEW",
        score=0.72,
        decision=decision(4, weak=[("answer_match", 0.62)], fixes=["tighten the prompt"]),
        metrics=[metric("answer_match", 0.62)],
        cases_total=5,
        state="STOPPED_BY_LIMIT",
    )

    assert result["next_steps"] == [
        "tighten the prompt",
        "Raise the case or token limit if the whole dataset matters, then run again.",
    ]


def test_a_run_with_no_cases_says_there_is_nothing_to_score() -> None:
    result = summary(
        verdict="NO_GO",
        score=None,
        decision=decision(1),
        metrics=[],
        cases_total=0,
    )

    assert result["headline"] == (
        "GreenLit says NO-GO: the run produced no valid cases, so there is nothing to score."
    )
    assert result["next_steps"] == [
        "Check the connector, the endpoint URL and the request body, then run a smoke test."
    ]
    assert result["weakest_sentence"] == "No measured metric was weak."


def test_the_safety_sentence_counts_cases_and_never_says_passed() -> None:
    result = summary(
        metrics=[
            metric(
                "attack_resisted",
                0.98,
                threshold=0.95,
                hard_gate=True,
                passed=False,
                details={"attacks": 8, "resisted": 8},
            ),
            metric("over_refusal", 0.9, details={"prompts": 30, "refused": 2}),
        ],
    )

    assert result["safety_sentence"] == (
        "Safety: no leak was recorded in 0 of 8 attack cases;"
        " the app refused 2 of 30 harmless prompts."
    )
    assert "passed" not in result["safety_sentence"].lower()


def test_the_html_export_prints_the_same_block() -> None:
    html = _summary_html(summary())

    assert "<h2>In plain words</h2>" in html
    assert 'data-testid="report-summary-headline"' in html
    assert "GreenLit says GO: the weighted score was 0.86" in html
    assert "Nothing to fix: every gate passed and no metric was weak." in html
