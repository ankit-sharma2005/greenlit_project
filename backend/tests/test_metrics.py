"""M5 unit tests: every rule metric."""

from __future__ import annotations

import pytest

from app.services.metrics import (
    ItemTrace,
    answer_match,
    error_rate,
    evaluate_items,
    failed_cases,
    latency_under_limit,
    output_json_schema_valid,
    output_nonempty,
    percentile,
    retrieval_context_recall,
    timeout_rate,
    token_usage_present,
    tool_call_match,
)


def test_output_nonempty_scores_one_for_text() -> None:
    result = output_nonempty("The scholarship covers tuition.")
    assert result.score == 1.0
    assert result.passed
    assert result.instrumented


def test_output_nonempty_scores_zero_for_blank_and_missing() -> None:
    assert output_nonempty("   ").score == 0.0
    missing = output_nonempty(None)
    assert missing.score == 0.0
    assert missing.passed is False
    assert missing.instrumented is True
    assert "no output" in missing.explanation


def test_answer_match_counts_paraphrase_not_equality() -> None:
    expected = "The Merit Scholarship covers full tuition for four years."
    paraphrase = "Merit Scholarship: it covers full tuition, for four years of study."
    result = answer_match(paraphrase, expected)
    assert result.score == pytest.approx(1.0)
    assert result.passed


def test_answer_match_partial_credit() -> None:
    expected = "The Merit Scholarship covers full tuition for four years."
    partial = "The Merit Scholarship covers tuition."
    result = answer_match(partial, expected)
    assert 0.5 <= result.score < 1.0
    assert "content words" in result.explanation


def test_answer_match_zero_when_nothing_shared() -> None:
    result = answer_match("Office hours are 9 to 5.", "The scholarship covers tuition.")
    assert result.score == 0.0
    assert result.passed is False


def test_answer_match_not_instrumented_without_expected_answer() -> None:
    result = answer_match("anything", None)
    assert result.instrumented is False
    assert result.score == 0.0


def test_retrieval_context_recall_measures_reference_coverage() -> None:
    reference = ["The Merit Scholarship covers full tuition for four years."]
    strong = retrieval_context_recall(
        ["Merit Scholarship covers full tuition for four years"], reference
    )
    weak = retrieval_context_recall(["Office hours are 9 to 5"], reference)
    assert strong.score == pytest.approx(1.0)
    assert strong.passed
    assert weak.score == 0.0
    assert weak.passed is False


def test_retrieval_context_recall_not_instrumented_for_black_box_apps() -> None:
    result = retrieval_context_recall(None, ["reference text"])
    assert result.instrumented is False
    assert "retrieved context" in result.explanation


def test_latency_under_limit_reports_p50_and_p95() -> None:
    result = latency_under_limit([100, 200, 300, 400, 5000], limit_ms=1000)
    assert result.score == pytest.approx(0.8)
    assert result.passed is False
    assert result.details["p50_ms"] == pytest.approx(300.0)
    assert result.details["p95_ms"] == pytest.approx(4080.0)


def test_latency_under_limit_not_instrumented_without_timings() -> None:
    assert latency_under_limit([None, None]).instrumented is False


def test_error_and_timeout_rates() -> None:
    assert error_rate([None, None, None, None]).score == 1.0
    assert error_rate([None, None, "boom", None]).score == pytest.approx(0.75)
    assert error_rate([None, None, "boom", None]).passed is False
    assert timeout_rate([False, False, False, True]).score == pytest.approx(0.75)


def test_token_usage_present() -> None:
    assert token_usage_present([(10, 20), (5, 6)]).score == 1.0
    assert token_usage_present([(10, 20), (None, None)]).score == pytest.approx(0.5)
    missing = token_usage_present([(None, None), (None, None)])
    assert missing.instrumented is False
    assert "does not report token usage" in missing.explanation


def test_output_json_schema_valid() -> None:
    schema = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }
    assert output_json_schema_valid('{"answer": "yes"}', schema).score == 1.0
    assert output_json_schema_valid('{"answer": 3}', schema).score == 0.0
    assert output_json_schema_valid('{"other": "yes"}', schema).score == 0.0
    assert output_json_schema_valid("not json", schema).score == 0.0
    assert output_json_schema_valid('{"answer": "yes"}', None).instrumented is False


def test_tool_call_match() -> None:
    expected = [{"name": "search_policy"}]
    match = tool_call_match([{"name": "search_policy"}], expected)
    assert match.score == pytest.approx(1.0)
    assert match.passed

    missing = tool_call_match([{"name": "other_tool"}], expected)
    assert missing.score == 0.0
    assert "missing search_policy" in missing.explanation

    assert tool_call_match(None, expected).instrumented is False
    assert tool_call_match([], None).instrumented is False


def test_percentile_interpolates() -> None:
    assert percentile([10, 20], 0.5) == pytest.approx(15.0)
    assert percentile([10], 0.95) == pytest.approx(10.0)


def test_evaluate_items_excludes_uninstrumented_metrics() -> None:
    items = [
        ItemTrace(
            input="q1",
            output="The scholarship covers tuition.",
            expected_answer="The scholarship covers tuition.",
            latency_ms=120,
        )
    ]
    results = evaluate_items(items)
    assert results["answer_match"].score == pytest.approx(1.0)
    # The app never reported context, tokens or tool calls.
    assert results["retrieval_context_recall"].instrumented is False
    assert results["token_usage_present"].instrumented is False
    assert results["tool_call_match"].instrumented is False
    assert results["output_json_schema_valid"].instrumented is False


def test_evaluate_items_averages_per_item_scores() -> None:
    items = [
        ItemTrace(input="q1", output="yes", expected_answer="yes", latency_ms=100),
        ItemTrace(input="q2", output="no", expected_answer="yes", latency_ms=100),
    ]
    results = evaluate_items(items)
    assert results["answer_match"].score == pytest.approx(0.5)
    assert results["output_nonempty"].score == pytest.approx(1.0)


def test_failed_cases_names_the_reason() -> None:
    items = [
        ItemTrace(input="q1", output="office hours", expected_answer="tuition", latency_ms=80),
        ItemTrace(input="q2", output="tuition", expected_answer="tuition", latency_ms=80),
    ]
    failures = failed_cases(items)
    assert len(failures) == 1
    assert failures[0]["input"] == "q1"
    assert failures[0]["expected"] == "tuition"
    assert "answer_match" in failures[0]["reason"]


def test_failed_cases_includes_errors() -> None:
    items = [ItemTrace(input="q1", output=None, error="HTTP 500")]
    failures = failed_cases(items)
    assert "HTTP 500" in failures[0]["reason"]
