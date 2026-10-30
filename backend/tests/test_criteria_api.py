"""Criteria overview endpoint (Settings -> Criteria).

The panel is only honest if it shows the engine's real numbers, so these tests
read the expected weights and thresholds from the engine itself instead of
restating them: a change to a profile must show up in the API or fail here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.criteria import (
    DEFAULT_GO_THRESHOLD,
    DEFAULT_REVIEW_THRESHOLD,
    DEFAULT_TEMPLATE_KEY,
    TEMPLATES,
    get_profile,
    with_judge,
    with_safety,
)
from app.services.criteria_overview import METRIC_GROUPS
from app.services.decision import DECISION_RULES, NOT_INSTRUMENTED_RULE

PASSWORD = "correct horse battery staple"


def _register(client: TestClient, email: str = "criteria@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Criteria Owner", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _payload(client: TestClient) -> dict[str, object]:
    _register(client)
    response = client.get("/api/v1/criteria")
    assert response.status_code == 200, response.text
    return response.json()


def test_criteria_requires_a_session(client: TestClient) -> None:
    response = client.get("/api/v1/criteria")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_thresholds_are_the_engines_own_values(client: TestClient) -> None:
    body = _payload(client)
    profile = get_profile(DEFAULT_TEMPLATE_KEY)

    assert body["review_threshold"] == profile.review_threshold
    assert body["go_threshold"] == profile.go_threshold
    # And those are the documented defaults, not a third copy of the numbers.
    assert body["review_threshold"] == DEFAULT_REVIEW_THRESHOLD
    assert body["go_threshold"] == DEFAULT_GO_THRESHOLD
    assert body["template"]["key"] == DEFAULT_TEMPLATE_KEY


def test_metric_weights_and_gates_match_the_engine(client: TestClient) -> None:
    body = _payload(client)
    # The panel shows what a New Test run with safety and a judge actually gets.
    profile = with_judge(with_safety(get_profile(DEFAULT_TEMPLATE_KEY)))
    expected = {criterion.metric: criterion for criterion in profile.criteria}

    rows = {row["name"]: row for row in body["criteria"]}  # type: ignore[union-attr]
    assert set(rows) == set(expected)
    for name, criterion in expected.items():
        row = rows[name]
        assert row["weight"] == criterion.weight
        assert row["hard_gate"] is criterion.hard_gate
        assert row["threshold"] == criterion.threshold
        if criterion.hard_gate:
            assert row["gate_threshold"] == criterion.threshold
        else:
            assert row["gate_threshold"] is None


def test_every_row_is_grouped_and_says_when_it_applies(client: TestClient) -> None:
    body = _payload(client)
    rows = {row["name"]: row for row in body["criteria"]}  # type: ignore[union-attr]

    assert rows["answer_match"]["group"] == "quality"
    assert rows["answer_quality"]["group"] == "quality"
    assert rows["attack_resisted"]["group"] == "safety"
    assert rows["over_refusal"]["group"] == "safety"
    assert rows["latency_under_limit"]["group"] == "operations"
    assert rows["error_rate"]["group"] == "operations"
    assert rows["timeout_rate"]["group"] == "operations"

    for name, row in rows.items():
        assert row["group"] == METRIC_GROUPS[name]
        assert row["group"] in {"quality", "safety", "operations"}
        assert row["applies"] in {"always", "safety on", "judge configured"}

    # The two conditional families are labelled as such, not presented as always on.
    assert rows["attack_resisted"]["applies"] == "safety on"
    assert rows["answer_quality"]["applies"] == "judge configured"
    assert rows["output_nonempty"]["applies"] == "always"


def test_the_safety_gate_is_a_hard_gate_in_the_overview(client: TestClient) -> None:
    body = _payload(client)
    rows = {row["name"]: row for row in body["criteria"]}  # type: ignore[union-attr]

    assert rows["attack_resisted"]["hard_gate"] is True
    assert rows["output_nonempty"]["hard_gate"] is True
    # Over-refusal lowers the score; it is not a gate of its own.
    assert rows["over_refusal"]["hard_gate"] is False


def test_rules_are_the_engines_rules_in_order(client: TestClient) -> None:
    body = _payload(client)
    rules = body["rules"]
    assert isinstance(rules, list)
    assert [rule["rule"] for rule in rules] == [1, 2, 3, 4, 5]
    assert [rule["verdict"] for rule in rules] == ["NO_GO", "NO_GO", "REVIEW", "REVIEW", "GO"]
    # The wording is the constant the engine documents, not a second copy.
    assert [rule["text"] for rule in rules] == [rule["text"] for rule in DECISION_RULES]
    for rule in rules:
        assert rule["text"].strip()


def test_not_instrumented_metrics_are_explained(client: TestClient) -> None:
    body = _payload(client)
    rule = body["not_instrumented_rule"]
    assert rule == NOT_INSTRUMENTED_RULE
    assert "never counted" in str(rule)


def test_templates_are_listed_with_their_counts(client: TestClient) -> None:
    body = _payload(client)
    templates = body["templates"]
    assert isinstance(templates, list)
    assert {entry["key"] for entry in templates} == set(TEMPLATES)
    for entry in templates:
        assert entry["criteria_count"] == len(TEMPLATES[entry["key"]].criteria)
        assert entry["name"] and entry["description"]
    assert body["default_template_key"] == DEFAULT_TEMPLATE_KEY
