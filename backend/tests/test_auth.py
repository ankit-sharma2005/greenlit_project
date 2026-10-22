from __future__ import annotations

import os

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a much better passphrase"


def register(client: TestClient, email: str = "ada@example.com", name: str = "Ada") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": name, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def cookie_header(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def test_register_first_user_is_admin_and_sets_http_only_cookies(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "Ada@Example.com", "name": "Ada", "password": PASSWORD},
    )

    assert response.status_code == 201
    user = response.json()["user"]
    assert user["role"] == "admin"
    assert user["email"] == "ada@example.com"

    cookies = cookie_header(response)
    assert any("greenlit_access=" in value and "HttpOnly" in value for value in cookies)
    assert any("greenlit_refresh=" in value and "HttpOnly" in value for value in cookies)
    assert all("SameSite=lax" in value for value in cookies)
    assert all("Secure" not in value for value in cookies)

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.com"


def test_second_user_is_member_and_duplicates_conflict(client: TestClient) -> None:
    register(client, "admin@example.com")
    member_response = client.post(
        "/api/v1/auth/register",
        json={"email": "member@example.com", "name": "Member", "password": PASSWORD},
    )
    assert member_response.status_code == 201
    assert member_response.json()["user"]["role"] == "member"

    duplicate = TestClient(client.app).post(
        "/api/v1/auth/register",
        json={"email": "member@example.com", "name": "Other", "password": PASSWORD},
    )
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["error"]["message"]


def test_short_password_is_rejected_with_field_errors(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "name": "Short", "password": "tiny"},
    )

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error"
    assert any(field["field"] == "password" for field in body["fields"])


def test_login_rejects_wrong_password_with_generic_message(client: TestClient) -> None:
    register(client)
    fresh = TestClient(client.app)

    response = fresh.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrong password"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Email or password is incorrect."


def test_logout_clears_cookies_and_ends_the_session(client: TestClient) -> None:
    register(client)

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    set_cookies = " ".join(cookie_header(response))
    assert 'greenlit_access=""' in set_cookies
    assert "Max-Age=0" in set_cookies
    assert client.get("/api/v1/auth/me").status_code == 401

    login = client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200


def test_refresh_rotates_tokens_and_detects_reuse(client: TestClient) -> None:
    register(client)
    original_refresh = client.cookies.get("greenlit_refresh")
    assert original_refresh

    rotated = client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    new_refresh = client.cookies.get("greenlit_refresh")
    assert new_refresh and new_refresh != original_refresh

    # Replaying the rotated token is treated as theft.
    client.cookies.set("greenlit_refresh", original_refresh)
    reuse = client.post("/api/v1/auth/refresh")
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "unauthorized"

    # The whole family is now revoked, including the previously valid token.
    client.cookies.set("greenlit_refresh", new_refresh)
    after_reuse = client.post("/api/v1/auth/refresh")
    assert after_reuse.status_code == 401


def test_missing_session_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Sign in to continue."


def test_member_cannot_use_admin_endpoints_but_admin_can(client: TestClient) -> None:
    register(client, "admin@example.com", "Admin")
    with TestClient(client.app) as member_client:
        register(member_client, "member@example.com", "Member")

        denied = member_client.get("/api/v1/users")
        assert denied.status_code == 403
        assert "role" in denied.json()["error"]["message"]

        assert member_client.get("/api/v1/audit").status_code == 403

        members = client.get("/api/v1/users")
        assert members.status_code == 200
        body = members.json()
        assert body["total"] == 2
        member_id = next(
            item["id"] for item in body["items"] if item["email"] == "member@example.com"
        )

        promoted = client.patch(f"/api/v1/users/{member_id}/role", json={"role": "reviewer"})
        assert promoted.status_code == 200
        assert promoted.json()["role"] == "reviewer"

        audit = client.get("/api/v1/audit")
        assert audit.status_code == 200
        actions = [event["action"] for event in audit.json()["items"]]
        assert "user.role_changed" in actions
        assert "auth.sign_in" not in actions


def test_last_admin_cannot_be_demoted(client: TestClient) -> None:
    admin = register(client, "admin@example.com")

    response = client.patch(f"/api/v1/users/{admin['id']}/role", json={"role": "member"})

    assert response.status_code == 409
    assert "last admin" in response.json()["error"]["message"]


def test_password_reset_debug_token_in_development(client: TestClient) -> None:
    from app.config import get_settings

    # Clear cached settings so env vars take effect
    get_settings.cache_clear()
    # Force development environment so debug_token is returned
    register(client)

    request = client.post("/api/v1/auth/password-reset/request", json={"email": "ada@example.com"})
    assert request.status_code == 200
    token = request.json()["debug_token"]
    assert token is not None, "debug_token should be set in development mode"


def test_password_reset_debug_token_not_in_production(client: TestClient) -> None:
    from app.config import get_settings

    # Clear cached settings so env vars take effect
    get_settings.cache_clear()
    # Force production environment so debug_token is NOT returned
    os.environ["APP_ENV"] = "production"
    os.environ.pop("DEBUG", None)
    register(client)

    request = client.post("/api/v1/auth/password-reset/request", json={"email": "ada@example.com"})
    assert request.status_code == 200
    token = request.json()["debug_token"]
    assert token is None, "debug_token must be None in production mode"


def test_password_reset_debug_token_with_debug_true(client: TestClient) -> None:
    from app.config import get_settings

    # Clear cached settings so env vars take effect
    get_settings.cache_clear()
    # Force production env but DEBUG=true should still return debug_token
    os.environ["APP_ENV"] = "production"
    os.environ["DEBUG"] = "true"
    register(client)

    request = client.post("/api/v1/auth/password-reset/request", json={"email": "ada@example.com"})
    assert request.status_code == 200
    token = request.json()["debug_token"]
    assert token is not None, "debug_token should be set when DEBUG=true even in production"

    # Clean up env vars
    del os.environ["DEBUG"]
    del os.environ["APP_ENV"]


def test_password_reset_is_single_use_and_revokes_sessions(client: TestClient) -> None:
    register(client)
    before_reset = client.cookies.get("greenlit_refresh")

    request = client.post("/api/v1/auth/password-reset/request", json={"email": "ada@example.com"})
    assert request.status_code == 200
    token = request.json()["debug_token"]
    assert token is not None, "debug_token should be set in development mode"

    unknown = client.post(
        "/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"}
    )
    assert unknown.status_code == 200
    assert unknown.json()["debug_token"] is None

    confirm = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert confirm.status_code == 200

    again = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    assert again.status_code == 400

    client.cookies.set("greenlit_refresh", before_reset or "")
    assert client.post("/api/v1/auth/refresh").status_code == 401

    fresh = TestClient(client.app)
    assert (
        fresh.post(
            "/api/v1/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        fresh.post(
            "/api/v1/auth/login", json={"email": "ada@example.com", "password": NEW_PASSWORD}
        ).status_code
        == 200
    )


def test_login_rate_limit_returns_429(client: TestClient) -> None:
    register(client)
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": "ada@example.com", "password": "definitely wrong"},
        )

    blocked = client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "definitely wrong"}
    )

    assert blocked.status_code == 429
    assert "Too many" in blocked.json()["error"]["message"]


def test_register_create_is_idempotent_under_duplicate_attempts(client: TestClient) -> None:
    register(client)
    second = client.post(
        "/api/v1/auth/register",
        json={"email": "ada@example.com", "name": "Ada Again", "password": PASSWORD},
    )

    assert second.status_code == 409
    users = client.get("/api/v1/users").json()
    assert users["total"] == 1
