"""Admin user management: who may call it, what it refuses, and what it never returns."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


def _register(client: TestClient, email: str, name: str = "Person") -> dict[str, Any]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def _new_client(client: TestClient) -> TestClient:
    return TestClient(client.app)


def test_member_and_reviewer_are_forbidden_and_anonymous_is_401(client: TestClient) -> None:
    admin = _register(client, "admin@example.com", "Admin")
    with _new_client(client) as member:
        _register(member, "member@example.com", "Member")
        assert member.get("/api/v1/users").status_code == 403
        denied_change = member.patch(f"/api/v1/users/{admin['id']}/role", json={"role": "member"})
        assert denied_change.status_code == 403

        promoted = client.patch(
            f"/api/v1/users/{_id_of(client, 'member@example.com')}/role", json={"role": "reviewer"}
        )
        assert promoted.status_code == 200

        # Same cookie, new role: still not an admin.
        assert member.get("/api/v1/users").status_code == 403

    with _new_client(client) as anonymous:
        assert anonymous.get("/api/v1/users").status_code == 401
        anonymous_change = anonymous.patch(
            f"/api/v1/users/{admin['id']}/role", json={"role": "member"}
        )
        assert anonymous_change.status_code == 401


def _id_of(client: TestClient, email: str) -> str:
    body = client.get("/api/v1/users").json()
    return next(item["id"] for item in body["items"] if item["email"] == email)


def test_search_filters_by_email_and_paging_is_bounded(client: TestClient) -> None:
    _register(client, "admin@example.com", "Admin")
    for index in range(3):
        with _new_client(client) as other:
            _register(other, f"person{index}@example.com", f"Person {index}")

    found = client.get("/api/v1/users", params={"search": "PERSON1@"})
    assert found.status_code == 200
    body = found.json()
    assert [item["email"] for item in body["items"]] == ["person1@example.com"]
    assert body["total"] == 1

    page = client.get("/api/v1/users", params={"limit": 2, "offset": 0})
    assert page.status_code == 200
    assert len(page.json()["items"]) == 2
    assert page.json()["total"] == 4

    assert client.get("/api/v1/users", params={"limit": 101}).status_code == 422
    assert client.get("/api/v1/users", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/users", params={"offset": -1}).status_code == 422


def test_an_admin_cannot_change_their_own_role(client: TestClient) -> None:
    first = _register(client, "first@example.com", "First")
    with _new_client(client) as second:
        _register(second, "second@example.com", "Second")
    second_admin = _id_of(client, "second@example.com")
    promoted = client.patch(f"/api/v1/users/{second_admin}/role", json={"role": "admin"})
    assert promoted.status_code == 200

    refused = client.patch(f"/api/v1/users/{first['id']}/role", json={"role": "member"})
    assert refused.status_code == 409
    assert "your own role" in refused.json()["error"]["message"]
    assert client.get("/api/v1/users").json()["items"][0]["role"] == "admin"


def test_the_last_admin_cannot_be_demoted(client: TestClient) -> None:
    admin = _register(client, "only@example.com", "Only")
    response = client.patch(f"/api/v1/users/{admin['id']}/role", json={"role": "member"})
    assert response.status_code == 409
    assert "last admin" in response.json()["error"]["message"]


def test_a_role_change_is_audited_and_carries_no_secret(client: TestClient) -> None:
    _register(client, "admin@example.com", "Admin")
    with _new_client(client) as member:
        _register(member, "changed@example.com", "Changed")
    target = _id_of(client, "changed@example.com")

    changed = client.patch(f"/api/v1/users/{target}/role", json={"role": "reviewer"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["role"] == "reviewer"

    events = client.get("/api/v1/audit").json()["items"]
    entry = next(event for event in events if event["action"] == "user.role_changed")
    assert entry["target_id"] == target
    assert entry["event_metadata"]["to"] == "reviewer"
    assert entry["event_metadata"]["from"] == "member"

    listing = client.get("/api/v1/users", params={"search": "changed@"})
    text = listing.text.lower()
    assert "password_hash" not in text
    assert "hash" not in text
    assert "token" not in text
    assert "session" not in text
    assert set(listing.json()["items"][0]) == {
        "id",
        "email",
        "name",
        "role",
        "is_active",
        "created_at",
    }


def test_an_unknown_user_and_an_unknown_role_are_refused(client: TestClient) -> None:
    _register(client, "admin@example.com", "Admin")
    unknown = client.patch(
        "/api/v1/users/00000000-0000-4000-8000-000000000000/role", json={"role": "member"}
    )
    assert unknown.status_code == 404
    with _new_client(client) as member:
        _register(member, "member@example.com", "Member")
    member_id = _id_of(client, "member@example.com")
    bad_role = client.patch(f"/api/v1/users/{member_id}/role", json={"role": "root"})
    assert bad_role.status_code == 422
