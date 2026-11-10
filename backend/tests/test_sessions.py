"""The Account tab's session list, and signing other devices out.

A session is one refresh-token family. These tests pin the four things that go
wrong: a row that cannot be recognised, a response that carries something secret,
another account's session being visible or revocable, and revoking others taking
the current session with it.
"""

from __future__ import annotations

import re
import uuid

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"
OWNER = "sessions@example.com"
CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0"
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")


def _register(client: TestClient, email: str = OWNER) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Session Owner", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _login(client: TestClient, user_agent: str, email: str = OWNER) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"user-agent": user_agent},
    )
    assert response.status_code == 200, response.text


def _sessions(client: TestClient) -> dict[str, object]:
    response = client.get("/api/v1/auth/sessions")
    assert response.status_code == 200, response.text
    return response.json()


def test_two_sign_ins_are_two_sessions_and_the_current_one_is_marked(
    client: TestClient,
) -> None:
    _register(client)
    _login(client, CHROME)

    body = _sessions(client)
    items = body["items"]

    assert body["total"] == 2
    assert len(items) == 2
    assert sum(1 for item in items if item["current"]) == 1
    devices = [item["device"] for item in items]
    assert "Chrome on Windows" in devices
    assert "Firefox on Linux" in devices or "Chrome on Windows" in devices


def test_each_device_is_labelled_from_its_own_agent(client: TestClient) -> None:
    _register(client)
    _login(client, CHROME)
    _login(client, FIREFOX)

    devices = [item["device"] for item in _sessions(client)["items"]]

    # Registration itself opens a session (the test client's own agent), so the two
    # logins are two more rows, each labelled from its own agent.
    assert "Chrome on Windows" in devices
    assert "Firefox on Linux" in devices
    assert len(devices) == 3


def test_a_missing_or_unreadable_agent_is_not_guessed(client: TestClient) -> None:
    _register(client)
    _login(client, "")
    _login(client, "curl/8.4.0")

    devices = [item["device"] for item in _sessions(client)["items"]]

    # An empty agent is "unknown device"; an agent that is neither a known browser
    # nor a known platform is "unrecognised browser" — neither is a guess.
    assert "unknown device" in devices
    assert "unrecognised browser" in devices
    assert len(devices) == 3


def test_the_response_carries_no_token_hash_or_ip(client: TestClient) -> None:
    _register(client)
    _login(client, CHROME)

    response = client.get("/api/v1/auth/sessions")

    assert response.status_code == 200
    assert HEX64.search(response.text) is None
    lowered = response.text.lower()
    for forbidden in ("token", "hash", "127.0.0.1", "ip_address", "user_agent"):
        assert forbidden not in lowered
    # What it does carry: an opaque id, a device label and two timestamps.
    item = response.json()["items"][0]
    assert set(item) == {"id", "device", "created_at", "last_activity", "current"}
    uuid.UUID(item["id"])


def test_another_account_cannot_see_or_revoke_a_session(client: TestClient) -> None:
    _register(client)
    _login(client, CHROME)
    other_family = next(item["id"] for item in _sessions(client)["items"] if item["current"])
    client.post("/api/v1/auth/logout")

    _register(client, email="stranger@example.com")

    assert _sessions(client)["total"] == 1  # only the stranger's own sign-in
    revoked = client.post(f"/api/v1/auth/sessions/{other_family}/revoke")
    assert revoked.status_code == 404
    assert revoked.json()["error"]["message"] == "Session not found."


def test_revoking_another_device_keeps_this_one_signed_in(client: TestClient) -> None:
    _register(client)
    # Keep the first device's cookies so we can prove they stopped working.
    first_device = dict(client.cookies)
    _login(client, CHROME)
    items = _sessions(client)["items"]
    other = next(item["id"] for item in items if not item["current"])

    response = client.post(f"/api/v1/auth/sessions/{other}/revoke")

    assert response.status_code == 200
    assert response.json()["message"] == "That device has been signed out."
    assert client.get("/api/v1/auth/me").status_code == 200
    remaining = _sessions(client)["items"]
    assert len(remaining) == 1 and remaining[0]["current"] is True

    # The signed-out device cannot refresh back in: its family is revoked.
    client.cookies.clear()
    client.cookies.update(first_device)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_revoking_the_current_session_behaves_like_sign_out(client: TestClient) -> None:
    _register(client)
    mine = next(item["id"] for item in _sessions(client)["items"] if item["current"])

    response = client.post(f"/api/v1/auth/sessions/{mine}/revoke")

    assert response.status_code == 200
    assert response.json()["message"] == "Signed out this device."
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/sessions").status_code == 401


def test_signing_out_every_other_device_keeps_the_current_family(
    client: TestClient,
) -> None:
    _register(client)
    _login(client, CHROME)
    _login(client, FIREFOX)

    response = client.post("/api/v1/auth/sessions/revoke-others")

    assert response.status_code == 200
    assert response.json()["revoked"] == 2
    assert client.get("/api/v1/auth/me").status_code == 200
    items = _sessions(client)["items"]
    assert len(items) == 1 and items[0]["current"] is True
    # The other devices' tokens are revoked, so calling it again has nothing to do.
    assert client.post("/api/v1/auth/sessions/revoke-others").json()["revoked"] == 0


def test_last_activity_moves_when_the_token_rotates(client: TestClient) -> None:
    _register(client)
    before = _sessions(client)["items"][0]

    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text

    after = _sessions(client)["items"][0]

    # Same session (same family id): the start stays, the newest token moves it on.
    assert after["id"] == before["id"]
    assert after["created_at"] == before["created_at"]
    assert after["last_activity"] >= before["last_activity"]
