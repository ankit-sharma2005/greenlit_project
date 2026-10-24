"""M5 unit tests: the decision engine, its rules and every boundary."""

from __future__ import annotations

import pytest

from app.services.criteria import (
    PLAIN_CHATBOT,
    RAG_CHATBOT,
    STRICT_SAFETY,
    TOOL_AGENT,
    CriteriaProfile,
    Criterion,
    get_profile,
    list_templates,
    profile_for,
)
from app.services.decision import (
    VERDICT_GO,
    VERDICT_NO_GO,
    VERDICT_REVIEW,
    JudgeStatus,
    RunSummary,
    decide,
    weighted_score,
)
from app.services.metrics import MetricResult


def result(name: str, score: float, instrumented: bool = True, passed: bool | None = None):
    return MetricResult(
        name=name,
        score=score,
        passed=(score >= 0.6 if passed is None else passed),
        explanation=f"{name} scored {score:.2f}",
        instrumented=instrumented,
    )


def single_metric_profile(
    review: float = 0.60, go: float = 0.80, hard_gate: bool = False
) -> CriteriaProfile:
    return CriteriaProfile(
        key="test",
        name="Test",
        description="one metric",
        criteria=(Criterion("answer_match", 1.0, 0.5, hard_gate=hard_gate),),
        review_threshold=review,
        go_threshold=go,
    )


def test_weighted_score_excludes_not_instrumented_metrics() -> None:
    results = {
        "answer_match": result("answer_match", 1.0),
        "retrieval_context_recall": result("retrieval_context_recall", 0.0, instrumented=False),
    }
    profile = CriteriaProfile(
        key="half",
        name="Half",
        description="",
        criteria=(
            Criterion("answer_match", 0.5, 0.5),
            Criterion("retrieval_context_recall", 0.5, 0.5),
        ),
    )
    assert weighted_score(results, profile) == pytest.approx(1.0)
    assert weighted_score({}, profile) is None


def test_weighted_score_uses_profile_weights() -> None:
    results = {"answer_match": result("answer_match", 0.5)}
    profile = CriteriaProfile(
        key="w",
        name="W",
        description="",
        criteria=(
            Criterion("answer_match", 0.75, 0.5),
            Criterion("output_nonempty", 0.25, 0.5),
        ),
    )
    assert weighted_score(results, profile) == pytest.approx(0.5)


def test_go_when_score_at_go_threshold() -> None:
    decision = decide(
        RunSummary(results={"answer_match": result("answer_match", 0.80)}, valid_items=5),
        single_metric_profile(),
    )
    assert decision.verdict == VERDICT_GO
    assert decision.rule == 5
    assert decision.score == pytest.approx(0.80)
    assert "GO threshold 0.80" in decision.reason


def test_review_when_score_exactly_at_review_threshold() -> None:
    decision = decide(
        RunSummary(results={"answer_match": result("answer_match", 0.60)}, valid_items=5),
        single_metric_profile(),
    )
    assert decision.verdict == VERDICT_REVIEW
    assert decision.rule == 4
    assert "between the REVIEW threshold 0.60 and the GO threshold 0.80" in decision.reason


def test_no_go_just_below_review_threshold() -> None:
    decision = decide(
        RunSummary(results={"answer_match": result("answer_match", 0.59)}, valid_items=5),
        single_metric_profile(),
    )
    assert decision.verdict == VERDICT_NO_GO
    assert decision.rule == 2


def test_review_just_below_go_threshold() -> None:
    decision = decide(
        RunSummary(results={"answer_match": result("answer_match", 0.79)}, valid_items=5),
        single_metric_profile(),
    )
    assert decision.verdict == VERDICT_REVIEW
    assert decision.rule == 4


def test_hard_gate_failure_is_no_go_even_with_high_score() -> None:
    profile = CriteriaProfile(
        key="gate",
        name="Gate",
        description="",
        criteria=(
            Criterion("answer_match", 0.5, 0.5),
            Criterion("output_nonempty", 0.5, 1.0, hard_gate=True),
        ),
    )
    results = {
        "answer_match": result("answer_match", 1.0),
        "output_nonempty": result("output_nonempty", 0.0, passed=False),
    }
    decision = decide(RunSummary(results=results, valid_items=3), profile)
    assert decision.verdict == VERDICT_NO_GO
    assert decision.rule == 1
    assert decision.hard_gate_failures == ("output_nonempty",)
    assert "Hard gate failed" in decision.reason
    # the explanation must still name the weighted score, the threshold and the weak metric
    assert "Weighted score 0.50" in decision.reason
    assert "REVIEW threshold 0.60" in decision.reason
    assert "output_nonempty 0.00" in decision.reason


def test_no_valid_items_is_no_go() -> None:
    decision = decide(
        RunSummary(results={"answer_match": result("answer_match", 0.0)}, valid_items=0),
        single_metric_profile(),
    )
    assert decision.verdict == VERDICT_NO_GO
    assert decision.rule == 1
    assert "no valid items" in decision.reason


def test_judge_unavailable_gives_review() -> None:
    decision = decide(
        RunSummary(
            results={"answer_match": result("answer_match", 0.95)},
            valid_items=5,
            judge=JudgeStatus(unavailable_items=2),
        ),
        single_metric_profile(),
    )
    assert decision.verdict == VERDICT_REVIEW
    assert decision.rule == 3
    assert "judge was unavailable for 2 item(s)" in decision.reason


def test_judge_low_confidence_gives_review() -> None:
    decision = decide(
        RunSummary(
            results={"answer_match": result("answer_match", 0.95)},
            valid_items=5,
            judge=JudgeStatus(low_confidence_items=1),
        ),
        single_metric_profile(),
    )
    assert decision.verdict == VERDICT_REVIEW
    assert decision.rule == 3


def test_judge_disagreement_within_tolerance_does_not_block_go() -> None:
    decision = decide(
        RunSummary(
            results={"answer_match": result("answer_match", 0.95)},
            valid_items=5,
            judge=JudgeStatus(disagreements=1, tolerance=1),
        ),
        single_metric_profile(),
    )
    assert decision.verdict == VERDICT_GO


def test_judge_disagreement_beyond_tolerance_gives_review() -> None:
    decision = decide(
        RunSummary(
            results={"answer_match": result("answer_match", 0.95)},
            valid_items=5,
            judge=JudgeStatus(disagreements=2, tolerance=1),
        ),
        single_metric_profile(),
    )
    assert decision.verdict == VERDICT_REVIEW


def test_go_names_the_weakest_metrics_and_fixes() -> None:
    profile = CriteriaProfile(
        key="two",
        name="Two",
        description="",
        criteria=(
            Criterion("answer_match", 0.5, 0.5),
            Criterion("latency_under_limit", 0.5, 0.9),
        ),
    )
    decision = decide(
        RunSummary(
            results={
                "answer_match": result("answer_match", 1.0),
                "latency_under_limit": result("latency_under_limit", 0.9),
            },
            valid_items=4,
        ),
        profile,
    )
    assert decision.verdict == VERDICT_GO
    assert decision.weak_metrics[0][0] == "latency_under_limit"
    assert any("latency is high" in fix for fix in decision.suggested_fixes)


def test_unmeasurable_run_is_no_go_with_a_clear_reason() -> None:
    profile = single_metric_profile()
    decision = decide(
        RunSummary(
            results={"answer_match": result("answer_match", 0.0, instrumented=False)},
            valid_items=4,
        ),
        profile,
    )
    assert decision.verdict == VERDICT_NO_GO
    assert "cannot be scored" in decision.reason


def test_templates_exist_and_have_sane_weights() -> None:
    keys = {profile.key for profile in list_templates()}
    assert keys == {"rag_chatbot", "plain_chatbot", "tool_agent", "strict_safety"}
    for profile in (RAG_CHATBOT, PLAIN_CHATBOT, TOOL_AGENT, STRICT_SAFETY):
        assert profile.review_threshold == 0.60
        assert profile.go_threshold == 0.80
        total = sum(criterion.weight for criterion in profile.criteria)
        assert total == pytest.approx(1.0, abs=0.001)
        assert any(criterion.hard_gate for criterion in profile.criteria)


def test_template_lookup_and_default_profile() -> None:
    assert get_profile("rag_chatbot") is RAG_CHATBOT
    assert profile_for(True) is RAG_CHATBOT
    assert profile_for(False) is PLAIN_CHATBOT
    with pytest.raises(ValueError):
        get_profile("nope")
