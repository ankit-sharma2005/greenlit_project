"""A cURL copied from a browser must not break the request it describes.

Chrome's "Copy as cURL" carries HTTP/2 pseudo-headers (``:authority``,
``:path``) and a ``Content-Length`` for the body it copied. GreenLit imports a
cURL's headers so a pasted session keeps working, and both of those made the
request fail before it reached the app:

* ``:authority`` — ``connector_error: Illegal header name b':authority'``;
* ``Content-Length`` — the rendered body has a different length than the copied
  one, so the client sent a stale length: ``connector_error: Too little data for
  declared Content-Length``, and a strict server answers 400/403.

The tests below run the real parser and the real connector against a local
server that records what it received.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

from app.services.connectors import HttpConnector
from app.utils.curl import clean_request_headers, parse_curl

CHROME_CURL = (
    "curl 'https://chat.example.test/api/message' \\\n"
    "  -X POST \\\n"
    "  -H ':authority: chat.example.test' \\\n"
    "  -H ':path: /api/message' \\\n"
    "  -H 'accept: application/json' \\\n"
    "  -H 'accept-encoding: gzip, deflate, br, zstd' \\\n"
    "  -H 'content-length: 61' \\\n"
    "  -H 'content-type: application/json' \\\n"
    "  -H 'cookie: session=abc; csrftoken=XYZ' \\\n"
    "  -H 'origin: https://chat.example.test' \\\n"
    "  -H 'referer: https://chat.example.test/chat' \\\n"
    "  -H 'x-csrftoken: XYZ' \\\n"
    '  --data-raw \'{"message":"hi"}\''
)


class _Capture(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, Any]]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        _Capture.seen.append(
            {
                "headers": {name.lower(): value for name, value in self.headers.items()},
                "body": body,
            }
        )
        payload = json.dumps({"answer": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:
        """Keep the test output readable."""


def _server_url() -> tuple[str, ThreadingHTTPServer]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Capture)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[:2]
    return f"http://{host}:{port}/api/message", httpd


def test_a_chrome_copy_keeps_the_session_headers_and_drops_client_owned_ones() -> None:
    parsed = parse_curl(CHROME_CURL)

    assert parsed is not None
    names = {name.lower() for name in parsed.headers}
    # What makes the request the same session the browser had:
    assert "cookie" in names
    assert "x-csrftoken" in names
    assert "origin" in names
    assert "referer" in names
    # What the client must derive itself:
    assert not names & {":authority", ":path", "content-length", "accept-encoding"}


def test_a_pasted_cookie_and_csrf_header_reach_the_target() -> None:
    parsed = parse_curl(CHROME_CURL)
    assert parsed is not None
    url, httpd = _server_url()
    _Capture.seen.clear()
    try:
        trace = HttpConnector(allow_private=True, min_delay_ms=0, max_retries=0).render_and_send(
            url=url,
            body_template=parsed.body_template or '{"question": {{input}}}',
            input_text="hello",
            headers=parsed.headers,
            timeout_seconds=5,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert trace.output == "ok"
    sent = _Capture.seen[-1]
    assert sent["headers"]["cookie"] == "session=abc; csrftoken=XYZ"
    assert sent["headers"]["x-csrftoken"] == "XYZ"
    assert sent["headers"]["origin"]
    # The body the target reads is GreenLit's rendered body, and its length
    # header agrees with it (no stale 61 from the copy).
    assert sent["headers"]["content-length"] == str(len(sent["body"]))
    assert json.loads(sent["body"]) == {"question": "hello"}


def test_a_target_saved_before_the_rule_is_healed_at_send_time() -> None:
    """An old saved target may still carry the copied headers; sending must work."""
    stale = {
        ":authority": "chat.example.test",
        ":path": "/api/message",
        "content-length": "61",
        "cookie": "session=abc",
    }
    cleaned = clean_request_headers(stale)
    assert cleaned == {"cookie": "session=abc"}

    url, httpd = _server_url()
    _Capture.seen.clear()
    try:
        trace = HttpConnector(allow_private=True, min_delay_ms=0, max_retries=0).render_and_send(
            url=url,
            body_template='{"question": {{input}}}',
            input_text="hello",
            headers=stale,
            timeout_seconds=5,
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert trace.output == "ok"
    assert _Capture.seen[-1]["headers"]["cookie"] == "session=abc"
