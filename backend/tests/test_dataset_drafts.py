"""Draft generation, per-item review and publish (PART 1, phase 3).

Every test uses a fake chat function: no network, no provider. The rules under
test are the ones the Review panel depends on — items start pending, malformed
output is rejected rather than stored, duplicates and PII are dropped, publishing
copies only approved items and keeps their provenance, and a 429 stops cleanly.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.services.generation import get_chat_fn
from app.services.llm_gateway import GatewayError

PASSWORD = "correct horse battery staple"


def register(client: TestClient, email: str = "draft@example.com", name: str = "Draft") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def make_provider(client: TestClient, name: str = "Draft generator", model: str = "llama3") -> dict:
    response = client.post(
        "/api/v1/providers",
        json={"name": name, "kind": "ollama", "model_name": model, "api_key": "sentinel-key-9"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def cases(*entries: dict) -> str:
    return json.dumps(list(entries))


def item(
    question: str = "What is the refund window?",
    answer: str = "Thirty days.",
    kind: str = "document_fact",
    passage: str | None = "Refunds are accepted for thirty days.",
) -> dict:
    return {
        "question": question,
        "expected_answer": answer,
        "source_passage": passage,
        "kind": kind,
    }


def use_chat(client: TestClient, reply: str | Exception) -> None:
    def fake(_provider, _messages, _temperature, _max_tokens) -> str:
        if isinstance(reply, Exception):
            raise reply
        return reply

    client.app.dependency_overrides[get_chat_fn] = lambda: fake


def clear_chat(client: TestClient) -> None:
    client.app.dependency_overrides.pop(get_chat_fn, None)


def create_draft(client: TestClient, provider_id: str, **overrides) -> dict:
    body = {
        "name": "Generated helpdesk",
        "app_description": "A support assistant for an online shop.",
        "count": 5,
        "kinds": ["document_fact", "unanswerable"],
        "provider_id": provider_id,
    }
    body.update(overrides)
    response = client.post("/api/v1/dataset-drafts", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_draft_stores_pending_items_with_provenance(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)
    use_chat(client, cases(item(), item(question="Can I cancel an order?")))
    try:
        draft = create_draft(client, provider["id"])
    finally:
        clear_chat(client)

    assert draft["status"] == "draft"
    assert draft["generated_by_model"] == "llama3"
    assert draft["generator_provider_name"] == "Draft generator"
    assert draft["prompt_version"] == "draft-v1"
    assert draft["same_as_judge"] is False
    assert [entry["status"] for entry in draft["items"]] == ["pending", "pending"]
    assert draft["items"][0]["prompt_version"] == "draft-v1"
    assert "sentinel-key-9" not in json.dumps(draft)


def test_malformed_output_is_rejected_and_nothing_is_stored(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)
    use_chat(client, "Sorry, I cannot do that.")
    try:
        response = client.post(
            "/api/v1/dataset-drafts",
            json={
                "name": "Bad draft",
                "app_description": "A shop assistant.",
                "count": 3,
                "kinds": ["document_fact"],
                "provider_id": provider["id"],
            },
        )
    finally:
        clear_chat(client)

    assert response.status_code == 422
    assert client.get("/api/v1/dataset-drafts").json()["total"] == 0


def test_duplicates_and_pii_are_dropped(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)
    use_chat(
        client,
        cases(
            item(question="What is the refund window?"),
            item(question="what is the refund window"),
            item(question="Email ada@example.com for help"),
            item(question="Call 555-010-9999 for support"),
            item(question="Can I cancel an order?", kind="unanswerable", passage=None),
        ),
    )
    try:
        draft = create_draft(client, provider["id"], count=5)
    finally:
        clear_chat(client)

    questions = [entry["question"] for entry in draft["items"]]
    assert questions == ["What is the refund window?", "Can I cancel an order?"]


def test_publishing_needs_an_approved_item(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)
    use_chat(client, cases(item()))
    try:
        draft = create_draft(client, provider["id"])
    finally:
        clear_chat(client)

    refused = client.post(f"/api/v1/dataset-drafts/{draft['id']}/publish")
    assert refused.status_code == 400
    assert "Approve at least one item" in refused.json()["error"]["message"]


def test_publish_copies_only_approved_items_and_keeps_provenance(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)
    use_chat(
        client,
        cases(
            item(question="Keep this one"),
            item(question="Reject this one"),
            item(question="Edit this one before use"),
        ),
    )
    try:
        draft = create_draft(client, provider["id"], count=3)
    finally:
        clear_chat(client)

    by_question = {entry["question"]: entry for entry in draft["items"]}
    first = by_question["Keep this one"]
    second = by_question["Reject this one"]
    third = by_question["Edit this one before use"]

    assert (
        client.patch(
            f"/api/v1/dataset-drafts/{draft['id']}/items/{first['id']}",
            json={"status": "approved"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/dataset-drafts/{draft['id']}/items/{second['id']}",
            json={"status": "rejected"},
        ).status_code
        == 200
    )
    edited = client.patch(
        f"/api/v1/dataset-drafts/{draft['id']}/items/{third['id']}",
        json={"question": "Edited question", "status": "approved"},
    )
    assert edited.status_code == 200
    edited_item = next(
        entry for entry in edited.json()["items"] if entry["question"] == "Edited question"
    )
    assert edited_item["edited"] is True
    assert edited_item["reviewed_at"] is not None

    published = client.post(f"/api/v1/dataset-drafts/{draft['id']}/publish")
    assert published.status_code == 201, published.text
    version = published.json()
    assert version["row_count"] == 2
    assert version["generated"] is True
    snapshot = version["columns_snapshot"]
    assert snapshot["generated_by_model"] == "llama3"
    assert snapshot["generator_provider"] == "Draft generator"
    assert snapshot["prompt_version"] == "draft-v1"
    assert snapshot["approved_items"] == 2
    assert snapshot["edited_items"] == 1

    items = client.get(
        f"/api/v1/datasets/{version['dataset_id']}/versions/{version['version_no']}/items"
    ).json()
    questions = [entry["data"]["question"] for entry in items["items"]]
    assert questions == ["Keep this one", "Edited question"]
    assert "Reject this one" not in questions

    # A second publish is refused rather than duplicating the dataset.
    assert client.post(f"/api/v1/dataset-drafts/{draft['id']}/publish").status_code == 409


def test_same_as_judge_is_flagged(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)
    client.patch(
        "/api/v1/auth/me/preferences",
        json={
            "theme": "dark",
            "judge": {"provider_id": provider["id"], "model": "llama3"},
            "generator": {"provider_id": provider["id"], "model": "llama3"},
        },
    )
    use_chat(client, cases(item()))
    try:
        draft = create_draft(client, provider["id"])
    finally:
        clear_chat(client)

    assert draft["same_as_judge"] is True


def test_a_rate_limited_generator_stops_cleanly(client: TestClient) -> None:
    register(client)
    provider = make_provider(client)
    use_chat(client, GatewayError("rate_limited", "The provider is rate limiting this account."))
    try:
        response = client.post(
            "/api/v1/dataset-drafts",
            json={
                "name": "Limited draft",
                "app_description": "A shop assistant.",
                "count": 2,
                "kinds": ["document_fact"],
                "provider_id": provider["id"],
            },
        )
    finally:
        clear_chat(client)

    assert response.status_code == 429
    assert client.get("/api/v1/dataset-drafts").json()["total"] == 0


def test_another_account_cannot_read_the_draft(client: TestClient) -> None:
    register(client, "first@example.com", "First")
    provider = make_provider(client)
    use_chat(client, cases(item()))
    try:
        draft = create_draft(client, provider["id"])
    finally:
        clear_chat(client)

    with TestClient(client.app) as second:
        register(second, "second@example.com", "Second")
        assert second.get(f"/api/v1/dataset-drafts/{draft['id']}").status_code == 404
        assert second.get("/api/v1/dataset-drafts").json()["total"] == 0
