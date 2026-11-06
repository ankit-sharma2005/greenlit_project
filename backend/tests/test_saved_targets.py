"""Saved targets (Settings → Connectors).

The rules this milestone promised: a saved target keeps the connector shape and
nothing that authorises a request, it belongs to one account, and a name repeated
under the same account is a clear 409 rather than a silent second row.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"

TARGET = {
    "name": "Support bot",
    "url": "https://support.example.com/ask",
    "method": "post",
    "body_template": '{"question": "{{question}}"}',
    "answer_path": "$.answer",
    "context_path": "$.sources",
    "response_format": "json",
}


def register(client: TestClient, email: str = "ada@example.com", name: str = "Ada") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def create(client: TestClient, **overrides: object) -> dict:
    response = client.post("/api/v1/saved-targets", json={**TARGET, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_saved_target_keeps_the_detected_format(client: TestClient) -> None:
    register(client)

    saved = create(client)

    assert saved["name"] == "Support bot"
    assert saved["connector_type"] == "http_endpoint"
    assert saved["method"] == "POST"  # stored upper-case, as a run sends it
    assert saved["answer_path"] == "$.answer"
    assert saved["context_path"] == "$.sources"
    assert saved["response_format"] == "json"
    # Polite-rate defaults travel with the target.
    assert (saved["timeout_seconds"], saved["max_concurrency"]) == (60, 1)
    assert (saved["min_delay_ms"], saved["max_retries"]) == (500, 3)
    assert saved["allow_private_targets"] is False
    assert saved["header_names"] == []

    listed = client.get("/api/v1/saved-targets").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == saved["id"]


def test_a_saved_target_rejects_a_header_value_or_a_permission_record(
    client: TestClient,
) -> None:
    register(client)

    # The shelf stores the shape of a request, never a value that can authorise
    # one, and never a permission record (that is asked per run).
    for extra in (
        {"headers": {"Authorization": "Bearer secret"}},
        {"headers_secret": "ciphertext"},
        {"permission_confirmed": True},
        {"owner_id": "00000000-0000-0000-0000-000000000000"},
    ):
        response = client.post("/api/v1/saved-targets", json={**TARGET, **extra})
        assert response.status_code == 422, extra
    assert client.get("/api/v1/saved-targets").json()["total"] == 0


def test_header_names_are_kept_without_duplicates_or_blanks(client: TestClient) -> None:
    register(client)

    saved = create(client, header_names=["Authorization", " ", "Authorization", " X-Tenant "])

    assert saved["header_names"] == ["Authorization", "X-Tenant"]


def test_a_repeated_name_is_a_conflict_in_plain_words(client: TestClient) -> None:
    register(client)
    create(client)

    again = client.post("/api/v1/saved-targets", json={**TARGET, "url": "https://b.example.com"})

    assert again.status_code == 409
    assert "already saved a target named" in again.json()["error"]["message"]
    assert client.get("/api/v1/saved-targets").json()["total"] == 1


def test_a_bad_url_or_blank_name_is_refused(client: TestClient) -> None:
    register(client)

    not_a_url = client.post("/api/v1/saved-targets", json={**TARGET, "url": "support.example.com"})
    assert not_a_url.status_code == 422
    assert "http(s)" in not_a_url.json()["error"]["message"]

    blank = client.post("/api/v1/saved-targets", json={**TARGET, "name": "   "})
    assert blank.status_code == 422
    assert client.get("/api/v1/saved-targets").json()["total"] == 0


def test_editing_changes_only_what_was_sent_and_can_clear_a_field(client: TestClient) -> None:
    register(client)
    saved = create(client)

    edited = client.patch(
        f"/api/v1/saved-targets/{saved['id']}",
        json={"name": "Support bot v2", "context_path": None, "response_format": "sse"},
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["name"] == "Support bot v2"
    assert body["context_path"] is None  # an explicit null clears it
    assert body["response_format"] == "sse"
    # Untouched fields keep their value.
    assert body["answer_path"] == "$.answer"
    assert body["url"] == TARGET["url"]


def test_another_account_cannot_read_or_change_a_target(client: TestClient) -> None:
    register(client)
    saved = create(client)

    with TestClient(client.app) as other:
        register(other, "grace@example.com", "Grace")
        assert other.get("/api/v1/saved-targets").json()["total"] == 0
        # Not even the existence leaks: a foreign id is a 404, not a 403.
        renamed = other.patch(f"/api/v1/saved-targets/{saved['id']}", json={"name": "Mine"})
        assert renamed.status_code == 404
        assert other.delete(f"/api/v1/saved-targets/{saved['id']}").status_code == 404

    assert client.get("/api/v1/saved-targets").json()["total"] == 1


def test_delete_removes_the_target_and_keeps_the_audit_trail(client: TestClient) -> None:
    register(client)
    saved = create(client)

    events = client.get("/api/v1/audit?action=saved_target").json()["items"]
    assert [event["action"] for event in events] == ["saved_target.create"]
    # The URL is not in the trail (a query string can carry a token).
    assert TARGET["url"] not in str(events[0]["event_metadata"])
    assert events[0]["event_metadata"]["response_format"] == "json"

    assert client.delete(f"/api/v1/saved-targets/{saved['id']}").status_code == 204
    assert client.get("/api/v1/saved-targets").json()["total"] == 0
    assert client.delete(f"/api/v1/saved-targets/{saved['id']}").status_code == 404

    # Newest first, like the audit screen.
    events = client.get("/api/v1/audit?action=saved_target").json()["items"]
    assert [event["action"] for event in events] == [
        "saved_target.delete",
        "saved_target.create",
    ]


def test_saved_targets_require_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/saved-targets").status_code == 401
    assert client.post("/api/v1/saved-targets", json=TARGET).status_code == 401
