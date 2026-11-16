"""A8: the site bot's cookie + CSRF rules and its nested reply shape."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
import requests
from site_bot.app import create_server


def _serve(server: Any) -> str:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture()
def site(tmp_path: Path) -> Any:
    server = create_server("normal", control_enabled=False, log_dir=tmp_path)
    url = _serve(server)
    yield url
    server.shutdown()
    server.server_close()


def _token(url: str) -> tuple[str, str]:
    page = requests.get(f"{url}/chat-page", timeout=10)
    assert page.status_code == 200
    assert "text/html" in page.headers["Content-Type"]
    cookies = page.cookies.get_dict()
    assert "session" in cookies and "csrf_token" in cookies
    assert cookies["csrf_token"] in page.text
    return cookies["session"], cookies["csrf_token"]


def test_health_shape(site: str) -> None:
    health = requests.get(f"{site}/health", timeout=10).json()
    assert health == {"status": "ok", "app": "site-bot", "mode": "normal"}


def test_the_page_sets_both_cookies_and_embeds_the_token(site: str) -> None:
    session, token = _token(site)
    assert len(session) >= 16 and len(token) >= 16


def test_chat_needs_both_the_cookie_and_the_header(site: str) -> None:
    missing = requests.post(f"{site}/api/chat", json={"message": "hi"}, timeout=10)
    assert missing.status_code == 403
    assert missing.json() == {"detail": "CSRF token missing"}

    wrong = requests.post(
        f"{site}/api/chat",
        json={"message": "hi"},
        headers={"X-CSRF-Token": "not-the-token"},
        cookies={"session": "abc", "csrf_token": "abc"},
        timeout=10,
    )
    assert wrong.status_code == 403

    token = _token(site)[1]
    right = requests.post(
        f"{site}/api/chat",
        json={"message": "What is your return policy?"},
        headers={"X-CSRF-Token": token},
        cookies={"session": token, "csrf_token": token},
        timeout=10,
    )
    assert right.status_code == 200
    body = right.json()
    assert body["data"]["reply"] == "Returns are accepted within 30 days."
    assert body["data"]["sources"] == ["returns.md", "policy.md"]


def test_unknown_questions_get_the_fixed_sentence(site: str) -> None:
    token = _token(site)[1]
    response = requests.post(
        f"{site}/api/chat",
        json={"message": "do you sell submarines"},
        headers={"X-CSRF-Token": token},
        cookies={"session": token, "csrf_token": token},
        timeout=10,
    )
    assert response.json()["data"] == {"reply": "I do not know.", "sources": []}


def test_csrf_off_mode_skips_the_check(tmp_path: Path) -> None:
    server = create_server("csrf_off", control_enabled=False, log_dir=tmp_path)
    url = _serve(server)
    try:
        response = requests.post(
            f"{url}/api/chat", json={"message": "hello"}, timeout=10
        )
        assert response.status_code == 200
        assert response.json()["data"]["reply"] == "I do not know."
    finally:
        server.shutdown()
        server.server_close()


def test_the_control_door_flips_the_mode(tmp_path: Path) -> None:
    server = create_server("normal", control_enabled=True, log_dir=tmp_path)
    url = _serve(server)
    try:
        flipped = requests.post(
            f"{url}/_control/mode", json={"mode": "csrf_off"}, timeout=10
        )
        assert flipped.status_code == 200
        assert requests.get(f"{url}/health", timeout=10).json()["mode"] == "csrf_off"
        unknown = requests.post(
            f"{url}/_control/mode", json={"mode": "open"}, timeout=10
        )
        assert unknown.status_code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_hostile_input_never_crashes_and_the_log_keeps_no_token(tmp_path: Path) -> None:
    server = create_server("csrf_off", control_enabled=False, log_dir=tmp_path)
    url = _serve(server)
    token = _token(url)[1]
    try:
        too_long = requests.post(
            f"{url}/api/chat", json={"message": "x" * 400}, timeout=10
        )
        assert too_long.status_code == 400
        empty = requests.post(f"{url}/api/chat", json={}, timeout=10)
        assert empty.status_code == 400
        malformed = requests.post(
            f"{url}/api/chat",
            data=b"nope",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert malformed.status_code == 400
        unicode = requests.post(
            f"{url}/api/chat", json={"message": "日本語 ✓"}, timeout=10
        )
        assert unicode.status_code == 200
        assert requests.get(f"{url}/chat-page", timeout=10).status_code == 200
    finally:
        server.shutdown()
        server.server_close()
    text = "".join(
        path.read_text(encoding="utf-8") for path in tmp_path.glob("*.jsonl")
    )
    assert token not in text
    assert "cookie" not in text.lower()
