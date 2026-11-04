"""Credentials from a pasted cURL: imported, encrypted, redacted, Host ignored.

A real company chatbot usually needs a session cookie and a bearer token. These
tests use a real local server that refuses anything without both, and the real
parse endpoint, so what is checked is exactly what a person's cURL does.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from app.services.run_executor import build_sender
from app.utils.curl import encrypt_headers, parse_curl

PASSWORD = "correct horse battery staple"
TOKEN = "tok-7f3a9c1e-super-secret"
COOKIE = "session=abc123def456"

CURL = (
    "curl 'https://chat.example.com/ask' "
    "-X POST "
    '-H "Content-Type: application/json" '
    f'-H "Authorization: Bearer {TOKEN}" '
    f'-b "{COOKIE}" '
    '-H "Host: attacker.example" '
    """-d '{"question": "{{input}}"}'"""
)


class _GuardedHandler(BaseHTTPRequestHandler):
    """Answers only with the right cookie and bearer token; records what it saw."""

    seen: ClassVar[list[dict[str, str]]] = []
    require_auth: ClassVar[bool] = True

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        seen = {
            "cookie": self.headers.get("Cookie") or "",
            "authorization": self.headers.get("Authorization") or "",
            "host": self.headers.get("Host") or "",
        }
        type(self).seen.append(seen)
        allowed = not type(self).require_auth or (
            COOKIE in seen["cookie"] and seen["authorization"] == f"Bearer {TOKEN}"
        )
        body = b'{"answer": "hello from the chatbot"}'
        self.send_response(200 if allowed else 401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def guarded() -> Iterator[tuple[str, type[_GuardedHandler]]]:
    _GuardedHandler.seen = []
    _GuardedHandler.require_auth = True
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _GuardedHandler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/chat", _GuardedHandler
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _register(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "curl@example.com", "name": "Curl User", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _parsed_secret(client: TestClient, curl: str) -> dict[str, object]:
    response = client.post("/api/v1/connectors/curl/parse", json={"curl": curl})
    assert response.status_code == 200, response.text
    return response.json()


def _test_with_secret(client: TestClient, url: str, headers_secret: str) -> tuple[int, str]:
    response = client.post(
        "/api/v1/connectors/test",
        json={
            "connector_type": "http_endpoint",
            "url": url,
            "body_template": '{"question": {{input}}}',
            "headers_secret": headers_secret,
            "allow_private_targets": True,
            "min_delay_ms": 0,
            "max_retries": 0,
            "timeout_seconds": 10,
            "auto_detect": False,
        },
    )
    return response.status_code, response.text


def test_parsed_curl_keeps_cookie_and_token_but_drops_host() -> None:
    parsed = parse_curl(CURL)
    assert parsed is not None
    assert parsed.headers["Authorization"] == f"Bearer {TOKEN}"
    assert parsed.headers["Cookie"] == COOKIE
    assert not any(name.lower() == "host" for name in parsed.headers)


def test_curl_url_after_explicit_method_is_parsed() -> None:
    parsed = parse_curl(
        "curl -X POST http://127.0.0.1:9501/chat "
        '-H "Content-Type: application/json" '
        '-d \'{"question":"What is GreenLit?"}\''
    )

    assert parsed is not None
    assert parsed.method == "POST"
    assert parsed.url == "http://127.0.0.1:9501/chat"
    assert parsed.body_template == '{"question": {{input}}}'


@pytest.mark.parametrize(
    ("curl", "expected_method", "expected_header_count"),
    [
        (
            'curl -X POST https://example.test/ask -H "A: b" -d \'{"q":"x"}\'',
            "POST",
            1,
        ),
        ("curl --request POST --url https://example.test/ask", "POST", 0),
        (
            'curl -H "A: b" -X POST \'https://example.test/ask\' --data-raw \'{"q":"x"}\'',
            "POST",
            1,
        ),
        (
            "curl 'https://example.test/ask' -H 'A: b' --data-raw '{\"q\":\"x\"}'",
            "POST",
            1,
        ),
        (
            'curl -L -s --compressed https://example.test/ask -d \'{"q":"x"}\'',
            "POST",
            0,
        ),
    ],
)
def test_curl_url_is_found_regardless_of_option_order(
    curl: str, expected_method: str, expected_header_count: int
) -> None:
    parsed = parse_curl(curl)

    assert parsed is not None
    assert parsed.method == expected_method
    assert parsed.url == "https://example.test/ask"
    assert parsed.header_count == expected_header_count


def test_curl_cookie_flag_becomes_a_cookie_header() -> None:
    parsed = parse_curl("curl 'https://example.com/ask' -b 'a=1; b=2' -b 'c=3'")
    assert parsed is not None
    assert parsed.headers["Cookie"] == "a=1; b=2; c=3"


def test_curl_basic_auth_is_sent_as_a_basic_header() -> None:
    parsed = parse_curl("curl 'https://example.com/ask' -u 'user:pass'")
    assert parsed is not None
    assert parsed.headers["Authorization"].startswith("Basic ")


def test_parsed_credentials_reach_a_guarded_target(
    client: TestClient, guarded: tuple[str, type[_GuardedHandler]]
) -> None:
    url, handler = guarded
    _register(client)

    parsed = client.post("/api/v1/connectors/curl/parse", json={"curl": CURL})
    assert parsed.status_code == 200, parsed.text
    document = parsed.json()
    # Names only: neither the token nor the cookie ever comes back.
    assert TOKEN not in parsed.text
    assert "abc123def456" not in parsed.text
    assert "Authorization" in document["header_names"]
    assert "Cookie" in document["header_names"]
    assert document["headers_secret"]

    status, text = _test_with_secret(client, url, document["headers_secret"])
    assert status == 200, text
    assert '"hello from the chatbot"' in text

    seen = handler.seen[-1]
    assert COOKIE in seen["cookie"]
    assert seen["authorization"] == f"Bearer {TOKEN}"
    # The pasted Host was dropped: the URL decides the host.
    assert seen["host"].startswith("127.0.0.1:")
    # And no response repeats the credentials.
    assert TOKEN not in text
    assert "abc123def456" not in text


def test_a_run_sends_the_same_encrypted_credentials(
    guarded: tuple[str, type[_GuardedHandler]],
) -> None:
    """The run path reads the encrypted blob through the same shared function."""
    url, handler = guarded
    snapshot = {
        "entry_point": "http_endpoint",
        "url": url,
        "method": "POST",
        "body_template": '{"question": {{input}}}',
        "answer_path": "answer",
        "allow_private_targets": True,
        "headers": {},
        "headers_encrypted": encrypt_headers(
            {"Authorization": f"Bearer {TOKEN}", "Cookie": COOKIE}
        ),
        "min_delay_ms": 0,
        "max_retries": 0,
        "timeout_seconds": 10,
    }
    sender = build_sender(snapshot, lambda: None)  # type: ignore[arg-type]
    trace = sender("hello")

    assert trace.output == "hello from the chatbot"
    seen = handler.seen[-1]
    assert COOKIE in seen["cookie"]
    assert seen["authorization"] == f"Bearer {TOKEN}"
    # The snapshot itself holds no readable credential.
    assert snapshot["headers"] == {}
    assert TOKEN not in str(snapshot["headers"])


def test_rejected_credentials_ask_for_a_fresh_curl(
    client: TestClient, guarded: tuple[str, type[_GuardedHandler]]
) -> None:
    url, _handler = guarded
    _register(client)
    # A stale session: the cookie is there, the bearer token is not.
    document = _parsed_secret(client, "curl 'https://chat.example.com/ask' -b 'session=expired'")

    status, text = _test_with_secret(client, url, str(document["headers_secret"]))
    assert status == 400, text
    assert "paste a fresh cURL" in text
    assert "expired" in text
    assert document["header_names"] == ["Cookie"]
