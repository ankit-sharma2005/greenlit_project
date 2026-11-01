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
    delay_answer = 0.0
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
        if type(self).delay_answer:
            time.sleep(type(self).delay_answer)
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
    _Handler.delay_answer = 0.0
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


def test_a_retried_case_records_the_final_attempt_and_the_wait_separately(
    server: tuple[str, type[_Handler]],
) -> None:
    """Latency is the successful attempt alone; retries and waits are their own fields."""
    url, handler = server
    handler.fail_times = 2
    handler.retry_after = None  # backoff, so the waits are real
    handler.delay_answer = 0.1

    started = time.monotonic()
    trace = _connector(max_retries=3).render_and_send(
        url=url,
        body_template='{"question": {{input}}}',
        input_text="hello",
        timeout_seconds=10,
    )
    total_ms = int((time.monotonic() - started) * 1000)

    assert trace.output == "ok"
    assert trace.retry_count == 2
    assert trace.waited_ms > 0
    # The recorded latency is the last attempt (~100 ms), not the two waits.
    assert 80 <= trace.latency_ms < total_ms
    assert trace.latency_ms < trace.waited_ms + 400


def test_zero_retries_sends_exactly_one_request(
    server: tuple[str, type[_Handler]],
) -> None:
    """max_retries = 0 is allowed, and means no duplicate side effects."""
    url, handler = server
    handler.always_fail = True
    with pytest.raises(ConnectorError) as caught:
        _connector(max_retries=0).render_and_send(
            url=url,
            body_template='{"question": {{input}}}',
            input_text="hello",
            timeout_seconds=5,
        )
    assert len(handler.statuses) == 1
    assert caught.value.details["status_code"] == 429


def test_a_cancel_interrupts_the_retry_wait(
    server: tuple[str, type[_Handler]],
) -> None:
    """A long Retry-After must not keep Cancel waiting."""
    url, handler = server
    handler.always_fail = True
    handler.retry_after = "30"
    interrupt = threading.Event()
    connector = HttpConnector(
        allow_private=True,
        min_delay_ms=0,
        max_retries=3,
        interrupt=interrupt,
    )
    threading.Timer(0.2, interrupt.set).start()

    started = time.monotonic()
    with pytest.raises(ConnectorError) as caught:
        connector.render_and_send(
            url=url,
            body_template='{"question": {{input}}}',
            input_text="hello",
            timeout_seconds=10,
        )
    elapsed = time.monotonic() - started

    assert caught.value.code == "cancelled"
    assert elapsed < 2.0, elapsed
    assert len(handler.statuses) == 1


def test_the_per_item_budget_ends_a_slow_case(
    server: tuple[str, type[_Handler]],
) -> None:
    """A target that dribbles past the budget fails with a structured timeout."""
    url, handler = server
    handler.delay_answer = 3.0
    connector = HttpConnector(
        allow_private=True,
        min_delay_ms=0,
        max_retries=0,
        item_budget_seconds=0.5,
    )

    started = time.monotonic()
    with pytest.raises(ConnectorError) as caught:
        connector.render_and_send(
            url=url,
            body_template='{"question": {{input}}}',
            input_text="hello",
            timeout_seconds=30,
        )
    elapsed = time.monotonic() - started

    assert caught.value.code == "timeout"
    assert "budget" in caught.value.message
    assert caught.value.details["timeout_seconds"] == 0.5
    # Well before the server's 3 s answer: the budget ended it.
    assert elapsed < 2.5, elapsed


def test_default_connector_waits_500_ms_and_tries_three_times() -> None:
    connector = HttpConnector(allow_private=True)
    assert connector.max_concurrency == 1
    assert connector.min_delay_ms == 500
    assert connector.max_retries == 3
    # A zero retry budget means exactly one attempt.
    assert RequestClient(allow_private_targets=True, max_retries=0).max_retries == 0
