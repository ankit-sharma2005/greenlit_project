"""M5 API tests: metric table, verdict explanation and the right-reason demo cases.

The demo is the college helpdesk (spec section 10): the good version must reach
GO, the broken version must reach NO_GO *and* explain itself by naming the
weighted score, the REVIEW threshold and the weak metrics.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.services.criteria import RAG_CHATBOT
from app.services.decision import VERDICT_GO, VERDICT_NO_GO, VERDICT_REVIEW
from app.services.evaluation import CaseData, evaluate_preview

PASSWORD = "correct horse battery"

EXPECTED = [
    (
        "What does the Merit Scholarship cover?",
        "The Merit Scholarship covers full tuition and fees for four years.",
        "Merit Scholarship covers full tuition and fees for four years",
        "The Merit Scholarship covers full tuition and fees for four years of study.",
    ),
    (
        "When is the library open?",
        "The library is open from 8 am to 10 pm on weekdays.",
        "Library open 8 am to 10 pm weekdays",
        "The library is open from 8 am until 10 pm on weekdays.",
    ),
    (
        "How do I appeal a grade?",
        "Submit a grade appeal form to the registrar within ten working days.",
        "Grade appeal form to the registrar within ten working days",
        "Submit a grade appeal form to the registrar within ten working days.",
    ),
]

BROKEN_ANSWERS = [
    "I am not sure about that.",
    "Please contact the department.",
    "No information available right now.",
]

BROKEN_CONTEXT = "Office hours are 9 to 5 in building C."


def good_cases() -> list[CaseData]:
    return [
        CaseData(
            input=question,
            expected_answer=expected,
            output=answer,
            retrieved_context=[context],
            reference_context=[context],
            latency_ms=420,
            tokens_in=120,
            tokens_out=60,
        )
        for question, expected, answer, context in EXPECTED
    ]


def broken_cases() -> list[CaseData]:
    return [
        CaseData(
            input=question,
            expected_answer=expected,
            output=BROKEN_ANSWERS[index],
            retrieved_context=[BROKEN_CONTEXT],
            reference_context=[context],
            latency_ms=9000,
        )
        for index, (question, expected, _answer, context) in enumerate(EXPECTED)
    ]


def register(client: TestClient, email: str = "ada@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Ada", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def test_templates_endpoint_lists_the_four_profiles(client: TestClient) -> None:
    register(client)
    response = client.get("/api/v1/evaluations/templates")
    assert response.status_code == 200, response.text
    body = response.json()
    keys = {template["key"] for template in body["templates"]}
    assert keys == {"rag_chatbot", "plain_chatbot", "tool_agent", "strict_safety"}
    assert body["default"] == "plain_chatbot"


def test_preview_requires_a_session(client: TestClient) -> None:
    response = client.post(
        "/api/v1/evaluations/preview", json={"cases": [{"input": "q", "output": "a"}]}
    )
    assert response.status_code == 401


def test_good_demo_outputs_get_go(client: TestClient) -> None:
    register(client)
    response = client.post(
        "/api/v1/evaluations/preview",
        json={
            "profile": "rag_chatbot",
            "cases": [
                {
                    "input": case.input,
                    "expected_answer": case.expected_answer,
                    "output": case.output,
                    "retrieved_context": case.retrieved_context,
                    "reference_context": case.reference_context,
                    "latency_ms": case.latency_ms,
                    "tokens_in": case.tokens_in,
                    "tokens_out": case.tokens_out,
                }
                for case in good_cases()
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == VERDICT_GO
    assert body["score"] >= 0.95
    assert body["failed_cases"] == []
    assert body["valid_items"] == 3


def test_broken_demo_outputs_get_no_go_for_the_right_reason(client: TestClient) -> None:
    register(client)
    response = client.post(
        "/api/v1/evaluations/preview",
        json={
            "profile": "rag_chatbot",
            "cases": [
                {
                    "input": case.input,
                    "expected_answer": case.expected_answer,
                    "output": case.output,
                    "retrieved_context": case.retrieved_context,
                    "reference_context": case.reference_context,
                    "latency_ms": case.latency_ms,
                }
                for case in broken_cases()
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["verdict"] == VERDICT_NO_GO
    reason = body["reason"]
    # The explanation must be usable on its own, not just a verdict string.
    assert re.search(r"Weighted score 0\.\d\d", reason), reason
    assert "below the REVIEW threshold 0.60" in reason
    assert "Weakest metrics:" in reason
    assert "answer_match 0.00" in reason
    assert "retrieval_context_recall 0.00" in reason

    metrics = {metric["name"]: metric for metric in body["metrics"]}
    assert metrics["answer_match"]["score"] == pytest.approx(0.0)
    assert metrics["answer_match"]["weight"] == pytest.approx(0.30)
    assert metrics["retrieval_context_recall"]["score"] == pytest.approx(0.0)
    # Black-box fields the app did not report are not instrumented and not zero.
    assert metrics["token_usage_present"]["instrumented"] is False

    assert body["suggested_fixes"], "the verdict must suggest fixes"
    assert any("retrieval recall" in fix for fix in body["suggested_fixes"])
    assert len(body["failed_cases"]) == 3
    assert "answer_match" in body["failed_cases"][0]["reason"]


def test_broken_demo_verdict_is_reproducible() -> None:
    first = evaluate_preview("rag_chatbot", broken_cases())
    second = evaluate_preview("rag_chatbot", broken_cases())
    assert first.decision == second.decision
    assert first.decision.verdict == VERDICT_NO_GO


def test_uninstrumented_metrics_are_excluded_from_the_score() -> None:
    preview = evaluate_preview("rag_chatbot", good_cases())
    assert preview.metrics_by_name()["token_usage_present"].instrumented is True
    assert preview.decision.score is not None
    assert preview.decision.score >= 0.95

    # The same cases, but the app reports no token usage: the metric is dropped
    # from the weighted score instead of counting as zero.
    silent = [
        CaseData(
            input=case.input,
            expected_answer=case.expected_answer,
            output=case.output,
            retrieved_context=case.retrieved_context,
            reference_context=case.reference_context,
            latency_ms=case.latency_ms,
        )
        for case in good_cases()
    ]
    without_tokens = evaluate_preview("rag_chatbot", silent)
    assert without_tokens.metrics_by_name()["token_usage_present"].instrumented is False
    assert without_tokens.decision.score is not None
    assert without_tokens.decision.score >= 0.95


def test_plain_chatbot_ignores_context() -> None:
    preview = evaluate_preview("plain_chatbot", good_cases())
    assert "retrieval_context_recall" not in preview.metrics_by_name()
    assert preview.decision.verdict == VERDICT_GO


def test_judge_unavailable_turns_a_passing_run_into_review(client: TestClient) -> None:
    from app.services.decision import JudgeStatus

    preview = evaluate_preview(
        "plain_chatbot", good_cases(), judge=JudgeStatus(unavailable_items=1)
    )
    assert preview.decision.verdict == VERDICT_REVIEW
    assert preview.decision.rule == 3


def test_preview_accepts_pasted_csv(client: TestClient) -> None:
    register(client)
    csv_text = (
        "input,expected_answer,output,reference_context,retrieved_context,latency_ms\n"
        "What does the Merit Scholarship cover?,"
        "The Merit Scholarship covers full tuition and fees for four years.,"
        "The Merit Scholarship covers full tuition and fees for four years,"
        "The Merit Scholarship covers full tuition and fees for four years.,"
        "Merit Scholarship covers full tuition and fees for four years,300\n"
    )
    response = client.post(
        "/api/v1/evaluations/preview",
        json={"profile": "rag_chatbot", "csv": csv_text},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["item_count"] == 1
    metrics = {metric["name"]: metric for metric in body["metrics"]}
    assert metrics["answer_match"]["score"] == pytest.approx(1.0)
    assert metrics["retrieval_context_recall"]["instrumented"] is True


def test_preview_rejects_an_unknown_profile(client: TestClient) -> None:
    register(client)
    response = client.post(
        "/api/v1/evaluations/preview",
        json={"profile": "nope", "cases": [{"input": "q", "output": "a"}]},
    )
    assert response.status_code == 400
    assert "Unknown criteria profile" in response.json()["error"]["message"]


def test_preview_rejects_empty_input(client: TestClient) -> None:
    register(client)
    response = client.post("/api/v1/evaluations/preview", json={"profile": "plain_chatbot"})
    assert response.status_code == 400


def test_rag_profile_defaults_match_the_spec() -> None:
    assert RAG_CHATBOT.review_threshold == 0.60
    assert RAG_CHATBOT.go_threshold == 0.80
    names = [criterion.metric for criterion in RAG_CHATBOT.criteria]
    assert names[:2] == ["answer_match", "retrieval_context_recall"]
