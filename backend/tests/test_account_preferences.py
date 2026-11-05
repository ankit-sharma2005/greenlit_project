"""Account profile and preference endpoints.

These cover the two rules the Settings page depends on: a user can only ever
change their own record (the target comes from the session), and a preference
belongs to one account rather than to the browser, so a second account signed
in on the same browser starts from the default.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


def register(client: TestClient, email: str = "ada@example.com", name: str = "Ada") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def test_preferences_default_to_dark_and_persist(client: TestClient) -> None:
    register(client)

    default = client.get("/api/v1/auth/me/preferences")
    assert default.status_code == 200
    assert default.json() == {"theme": "dark"}

    saved = client.patch("/api/v1/auth/me/preferences", json={"theme": "light"})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"theme": "light"}
    assert client.get("/api/v1/auth/me/preferences").json() == {"theme": "light"}


def test_preferences_are_isolated_between_accounts(client: TestClient) -> None:
    register(client, "first@example.com", "First")
    client.patch("/api/v1/auth/me/preferences", json={"theme": "light"})

    with TestClient(client.app) as second:
        register(second, "second@example.com", "Second")
        # A different account on the same browser does not inherit the choice.
        assert second.get("/api/v1/auth/me/preferences").json() == {"theme": "dark"}
        second.patch("/api/v1/auth/me/preferences", json={"theme": "system"})
        assert second.get("/api/v1/auth/me/preferences").json() == {"theme": "system"}

    # And the first account kept its own value.
    assert client.get("/api/v1/auth/me/preferences").json() == {"theme": "light"}


def test_preferences_reject_unknown_theme_and_unknown_keys(client: TestClient) -> None:
    register(client)

    unknown_theme = client.patch("/api/v1/auth/me/preferences", json={"theme": "neon"})
    assert unknown_theme.status_code == 422
    assert any(field["field"] == "theme" for field in unknown_theme.json()["error"]["fields"])

    extra_key = client.patch("/api/v1/auth/me/preferences", json={"theme": "dark", "density": 2})
    assert extra_key.status_code == 422

    # Neither call stored anything.
    assert client.get("/api/v1/auth/me/preferences").json() == {"theme": "dark"}


def test_preferences_require_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me/preferences").status_code == 401
    assert client.patch("/api/v1/auth/me/preferences", json={"theme": "light"}).status_code == 401


def test_profile_update_changes_only_the_display_name(client: TestClient) -> None:
    user = register(client, "ada@example.com", "Ada")
    assert user["role"] == "admin"

    updated = client.patch("/api/v1/auth/me", json={"name": "  Ada Lovelace  "})
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["name"] == "Ada Lovelace"  # trimmed, not blank
    assert body["email"] == "ada@example.com"
    assert body["role"] == "admin"
    assert body["id"] == user["id"]

    assert client.get("/api/v1/auth/me").json()["name"] == "Ada Lovelace"

    events = client.get("/api/v1/audit?action=profile_updated").json()["items"]
    assert [event["action"] for event in events] == ["user.profile_updated"]
    assert events[0]["event_metadata"] == {"changed": ["name"]}

    # Email and role are not part of this endpoint; extras are rejected, so a
    # request cannot grant itself a role.
    for payload in (
        {"name": "Someone Else", "role": "admin"},
        {"name": "Someone Else", "email": "attacker@example.com"},
    ):
        response = client.patch("/api/v1/auth/me", json=payload)
        assert response.status_code == 422
    assert client.get("/api/v1/auth/me").json()["email"] == "ada@example.com"


def test_blank_display_name_is_rejected_with_a_field_error(client: TestClient) -> None:
    register(client)

    response = client.patch("/api/v1/auth/me", json={"name": "   "})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert any(field["field"] == "name" for field in error["fields"])
    assert client.get("/api/v1/auth/me").json()["name"] == "Ada"


def test_profile_update_requires_a_session(client: TestClient) -> None:
    response = client.patch("/api/v1/auth/me", json={"name": "Nobody"})
    assert response.status_code == 401
