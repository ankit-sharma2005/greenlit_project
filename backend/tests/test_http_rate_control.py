"""Polite rate control: retries, Retry-After and the minimum gap between requests.

Everything here runs against a real local HTTP server: the connector's retry and
pacing behaviour is what a company chatbot actually experiences.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from app.services.connectors import ConnectorError, HttpConnector
from app.services.error_kinds import HTTP_ERROR
from app.utils.request_client import (
    RETRY_AFTER_CAP_SECONDS,
    RequestClient,
    retry_after_seconds,
)

BODY = b'{"answer": "ok"}'


class _Handler(BaseHTTPRequestHandler):
    """Configurable: answer 429 a few times, or always, and record request times."""

    fail_times = 0
    retry_after: str | None = "0"
    always_fail = False
    statuses: ClassVar[list[int]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        type(self).statuses.append(1)
        attempt = len(type(self).statuses)
        failing = type(self).always_fail or attempt <= type(self).fail_times
        if failing:
            self.send_response(429)
            if type(self).retry_after is not None:
                self.send_header("Retry-After", type(self).retry_after)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def server() -> Iterator[tuple[str, type[_Handler]]]:
    _Handler.statuses = []
    _Handler.fail_times = 0
    _Handler.always_fail = False
    _Handler.retry_after = "0"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/chat", _Handler
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _connector(*, min_delay_ms: int = 0, max_retries: int = 3) -> HttpConnector:
    return HttpConnector(
        allow_private=True,
        min_delay_ms=min_delay_ms,
        max_retries=max_retries,
    )


def test_429_with_retry_after_twice_then_succeeds(
    server: tuple[str, type[_Handler]],
) -> None:
    url, handler = server
    handler.fail_times = 2
    trace = _connector().render_and_send(
        url=url,
        body_template='{"question": {{input}}}',
        input_text="hello",
        timeout_seconds=5,
    )
    assert trace.output == "ok"
    assert len(handler.statuses) == 3


def test_always_429_keeps_its_structured_error(
    server: tuple[str, type[_Handler]],
) -> None:
    url, handler = server
    handler.always_fail = True
    with pytest.raises(ConnectorError) as caught:
        _connector(max_retries=2).render_and_send(
            url=url,
            body_template='{"question": {{input}}}',
            input_text="hello",
            timeout_seconds=5,
        )
    error = caught.value
    assert error.code == "http_error"
    assert error.kind == HTTP_ERROR
    assert error.details["status_code"] == 429
    # The first attempt plus two retries, then the real failure is kept.
    assert len(handler.statuses) == 3


def test_min_delay_is_respected_between_requests(
    server: tuple[str, type[_Handler]],
) -> None:
    url, handler = server
    starts: list[float] = []
    original = handler.do_POST

    def recording(self: _Handler) -> None:
        starts.append(time.monotonic())
        original(self)

    handler.do_POST = recording  # type: ignore[method-assign]
    connector = _connector(min_delay_ms=200)
    for _ in range(3):
        connector.render_and_send(
            url=url,
            body_template='{"question": {{input}}}',
            input_text="hello",
            timeout_seconds=5,
        )
    assert len(starts) == 3
    gaps = [later - earlier for earlier, later in itertools.pairwise(starts)]
    assert all(gap >= 0.18 for gap in gaps), gaps


def test_http_date_retry_after_is_understood_and_capped() -> None:
    soon = format_datetime(datetime.now(UTC) + timedelta(seconds=5), usegmt=True)
    waited = retry_after_seconds(soon)
    assert waited is not None
    assert 3.0 <= waited <= 5.0

    far = format_datetime(datetime.now(UTC) + timedelta(hours=2), usegmt=True)
    assert retry_after_seconds(far) == RETRY_AFTER_CAP_SECONDS

    past = format_datetime(datetime.now(UTC) - timedelta(minutes=1), usegmt=True)
    assert retry_after_seconds(past) == 0.0

    assert retry_after_seconds("12") == 12.0
    assert retry_after_seconds("not a date") is None
    assert retry_after_seconds(None) is None


def test_default_connector_waits_500_ms_and_tries_three_times() -> None:
    connector = HttpConnector(allow_private=True)
    assert connector.max_concurrency == 1
    assert connector.min_delay_ms == 500
    assert connector.max_retries == 3
    # A zero retry budget means exactly one attempt.
    assert RequestClient(allow_private_targets=True, max_retries=0).max_retries == 0
