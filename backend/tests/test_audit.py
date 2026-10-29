"""Audit log filters (admin only).

The audit screen pages and filters on the server, so these tests check that the
filter narrows the *total* as well as the page (a filter that only hides rows
would make "1-20 of 300" a lie) and that the newest event comes first.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


def _register(client: TestClient, email: str, name: str = "Person") -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _strip_pagination(client: TestClient, query: str = "") -> dict[str, object]:
    response = client.get(f"/api/v1/audit{query}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_filter_narrows_the_total_and_the_page(client: TestClient) -> None:
    admin = _register(client, "audit@example.com", "Admin")
    member = _register(client, "audit-member@example.com", "Member")
    client.post("/api/v1/auth/login", json={"email": "audit@example.com", "password": PASSWORD})
    changed = client.patch(
        f"/api/v1/users/{member['user']['id']}/role",  # type: ignore[index]
        json={"role": "reviewer"},
    )
    assert changed.status_code == 200, changed.text

    everything = _strip_pagination(client)
    assert everything["total"] >= 4  # register x2, sign-in, role change

    auth_only = _strip_pagination(client, "?action=auth")
    actions = [item["action"] for item in auth_only["items"]]  # type: ignore[index]
    assert actions and all("auth" in action for action in actions)
    assert "user.role_changed" not in actions
    # The total counts the filtered set, not the whole log.
    assert auth_only["total"] == len(actions)

    users = _strip_pagination(client, "?target_type=user")
    assert all(item["target_type"] == "user" for item in users["items"])  # type: ignore[index]
    assert "user.role_changed" in [item["action"] for item in users["items"]]  # type: ignore[index]

    role_changes = _strip_pagination(client, "?action=role_changed")
    assert [item["action"] for item in role_changes["items"]] == ["user.role_changed"]  # type: ignore[index]

    assert admin["user"]["role"] == "admin"  # type: ignore[index]


def test_the_newest_event_comes_first_and_pages_do_not_overlap(client: TestClient) -> None:
    _register(client, "paging@example.com", "Admin")
    client.post("/api/v1/auth/login", json={"email": "paging@example.com", "password": PASSWORD})

    first = _strip_pagination(client, "?limit=1&offset=0")
    second = _strip_pagination(client, "?limit=1&offset=1")

    assert first["total"] == second["total"]
    first_id = first["items"][0]["id"]  # type: ignore[index]
    second_id = second["items"][0]["id"]  # type: ignore[index]
    assert first_id != second_id
    # The sign-in happened last, so it is the first row.
    assert first["items"][0]["action"] == "auth.sign_in"  # type: ignore[index]


def test_a_non_admin_cannot_read_the_audit_log(client: TestClient) -> None:
    _register(client, "admin@example.com", "Admin")
    client.cookies.clear()
    _register(client, "member@example.com", "Member")

    assert client.get("/api/v1/audit?action=auth").status_code == 403
