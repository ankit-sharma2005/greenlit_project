"""Structured target errors: kind, status, host+path and a redacted snippet.

A failed case used to say only "Response was not valid JSON" or "wrong answer
path", which made a 422 look like a quality problem. These tests drive a real
local server (not a mocked string) so the status, the target and the body really
travel from the HTTP call to the stored detail, and a credential in the body
cannot leak into a report.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest

from app.models import Provider
from app.services.connectors import ConnectorError, HttpConnector
from app.services.error_kinds import CONNECTION, HTTP_ERROR, INVALID_RESPONSE, TIMEOUT
from app.services.llm_gateway import GatewayError, LLMGateway
from app.services.target_error import describe, error_detail, redact_snippet, target_of

TOKEN = "supersecrettoken12345"


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_target_keeps_host_port_and_path_but_no_query_string() -> None:
    assert target_of("http://127.0.0.1:8080/chat?api_key=abc&x=1") == "127.0.0.1:8080/chat"
    assert target_of("https://user:pw@example.com:443/v1/ask#frag") == "example.com:443/v1/ask"
    assert target_of("http://example.com") == "example.com/"
    assert target_of("") == ""


def test_redaction_removes_bearer_tokens_and_keys() -> None:
    text = f'Authorization: Bearer {TOKEN}, "api_key": "sk-secretvalue1234", token={TOKEN}'
    cleaned = redact_snippet(text)
    assert TOKEN not in cleaned
    assert "secretvalue1234" not in cleaned
    assert "[redacted]" in cleaned


def test_redaction_is_bounded_and_single_line() -> None:
    cleaned = redact_snippet("line one\n\nline two " * 100)
    assert len(cleaned) <= 300
    assert "\n" not in cleaned
    assert cleaned.endswith("…")


def test_describe_names_the_status_target_and_snippet() -> None:
    http_line = describe(
        HTTP_ERROR, "bad request", status=422, target="app.local/ask", snippet='{"detail":"no"}'
    )
    assert "HTTP 422" in http_line
    assert "app.local/ask" in http_line
    assert '{"detail":"no"}' in http_line

    assert "refused the connection" in describe(CONNECTION, "boom", target="app.local/ask")
    timeout_line = describe(TIMEOUT, "slow", target="app.local/ask", timeout_seconds=30)
    assert "Timed out after 30 s" in timeout_line
    invalid = describe(INVALID_RESPONSE, "no json", target="app.local/ask", snippet="<html>")
    assert "could not be read" in invalid


def test_error_detail_is_redacted_even_when_built_directly() -> None:
    detail = error_detail(
        kind=HTTP_ERROR,
        message="HTTP 401",
        status=401,
        target="app.local/ask",
        snippet=f"Bearer {TOKEN}",
    )
    assert detail["status"] == 401
    assert detail["target"] == "app.local/ask"
    assert TOKEN not in detail["snippet"]
    assert TOKEN not in detail["summary"]


# --------------------------------------------------------------------------- #
# A real server that answers like a misconfigured app
# --------------------------------------------------------------------------- #


class _Handler(BaseHTTPRequestHandler):
    """Answers by path: 404, 422, 500, HTML 200, JSON 200 and a 401 that leaks."""

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        path = self.path.split("?")[0]
        status, ctype, body = {
            "/404": (404, "application/json", '{"detail":"no such route"}'),
            "/422": (422, "application/json", '{"detail":"question is required"}'),
            "/500": (500, "text/plain", "Traceback: connection to db lost"),
            "/html": (200, "text/html", "<html><body>Not an API</body></html>"),
            "/ok": (200, "application/json", '{"answer":"42"}'),
            "/leak": (
                401,
                "application/json",
                f'{{"error":"bad token Bearer {TOKEN}"}}',
            ),
        }.get(path, (200, "application/json", '{"answer":"42"}'))
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        """Keep the test output clean."""


@pytest.fixture
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _connector() -> HttpConnector:
    return HttpConnector(allow_private=True)


def _send(connector: HttpConnector, url: str) -> ConnectorError:
    with pytest.raises(ConnectorError) as caught:
        connector.render_and_send(
            url=url,
            body_template='{"question": {{input}}}',
            input_text="hello",
            timeout_seconds=5,
        )
    return caught.value


def test_404_keeps_its_message_and_now_carries_status_and_snippet(server: str) -> None:
    error = _send(_connector(), f"{server}/404")
    assert error.code == "not_found"
    assert "this path does not exist" in error.message
    assert error.details["status_code"] == 404
    assert error.details["target"].endswith("/404")
    assert "no such route" in error.details["snippet"]


def test_422_is_an_http_error_not_a_wrong_answer_path(server: str) -> None:
    error = _send(_connector(), f"{server}/422")
    assert error.kind == HTTP_ERROR
    assert error.code == "http_error"
    # The old behaviour fell through to "wrong answer path", which blamed the
    # answer instead of the request shape.
    assert error.code != "wrong_answer_path"
    assert error.details["status_code"] == 422
    assert "question is required" in error.details["snippet"]


def test_500_carries_the_body_snippet(server: str) -> None:
    error = _send(_connector(), f"{server}/500")
    assert error.kind == HTTP_ERROR
    assert error.details["status_code"] == 500
    assert "connection to db lost" in error.details["snippet"]


def test_a_200_that_is_html_is_invalid_json_with_the_body(server: str) -> None:
    error = _send(_connector(), f"{server}/html")
    assert error.code == "invalid_json"
    assert error.kind == INVALID_RESPONSE
    assert "Not an API" in error.details["snippet"]
    assert error.details["target"].endswith("/html")


def test_a_token_in_the_target_body_never_reaches_the_detail(server: str) -> None:
    error = _send(_connector(), f"{server}/leak")
    assert error.details["status_code"] == 401
    assert TOKEN not in error.details["snippet"]
    assert "[redacted]" in error.details["snippet"]


def test_connection_refused_is_a_connection_error() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    error = _send(_connector(), f"http://127.0.0.1:{port}/ask")
    assert error.kind == CONNECTION
    assert error.details["target"] == f"127.0.0.1:{port}/ask"


def test_the_query_string_never_lands_in_the_detail(server: str) -> None:
    error = _send(_connector(), f"{server}/422?token={TOKEN}")
    assert TOKEN not in error.details["target"]
    assert "?" not in error.details["target"]


# --------------------------------------------------------------------------- #
# The gateway records the same three facts
# --------------------------------------------------------------------------- #


def _provider() -> Provider:
    return Provider(
        name="status-test",
        kind="openai-compatible",
        model_name="fake-model",
        base_url="http://127.0.0.1:9999/v1",
        is_active=True,
        max_retries=0,
        timeout_seconds=5,
    )


def _reply(status: int, body: str) -> httpx.Response:
    return httpx.Response(
        status,
        text=body,
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "http://test"),
    )


def test_gateway_http_error_carries_status_target_and_redacted_snippet() -> None:
    gateway = LLMGateway(post=lambda *a, **k: _reply(500, f'{{"error":"Bearer {TOKEN}"}}'))
    with pytest.raises(GatewayError) as caught:
        gateway.chat(_provider(), [{"role": "user", "content": "hi"}])
    error = caught.value
    assert error.kind == HTTP_ERROR
    assert error.details["status_code"] == 500
    assert error.details["target"] == "127.0.0.1:9999/v1/chat/completions"
    assert TOKEN not in error.details["snippet"]


def test_gateway_invalid_response_keeps_a_snippet() -> None:
    gateway = LLMGateway(post=lambda *a, **k: _reply(200, json.dumps({"unexpected": True})))
    with pytest.raises(GatewayError) as caught:
        gateway.chat(_provider(), [{"role": "user", "content": "hi"}])
    assert caught.value.kind == INVALID_RESPONSE
    assert "unexpected" in caught.value.details["snippet"]
