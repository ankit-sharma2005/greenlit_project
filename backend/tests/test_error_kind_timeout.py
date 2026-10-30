"""Structured failure kinds: real timeout, real refusal, and the old-run fallback.

The timeout rate used to be guessed from the error text. These tests prove the
replacement against a real socket: a local server that sleeps past the timeout
must be a ``timeout``, a port nobody listens on must be a ``connection``, and a
run recorded before the label existed still reads correctly from its text.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app.services.connectors import ConnectorError, HttpConnector
from app.services.error_kinds import (
    CONNECTION,
    ERROR_KINDS,
    HTTP_ERROR,
    OTHER,
    TIMEOUT,
    kind_for_code,
)
from app.services.operations import ItemSample, compute_operations, samples_from_items

RESPONSE_BODY = b'{"answer": "late but correct"}'


def _free_port() -> int:
    """A port that nothing listens on (bound then released)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _SlowHandler(BaseHTTPRequestHandler):
    """Answers correctly, but only after the connector has given up."""

    def do_POST(self) -> None:
        time.sleep(2.0)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(RESPONSE_BODY)))
        self.end_headers()
        self.wfile.write(RESPONSE_BODY)

    def log_message(self, *args: object) -> None:  # keep the test output clean
        return


@pytest.fixture
def slow_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/ask"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _connector() -> HttpConnector:
    # The test server is on loopback, which the request client refuses by default.
    return HttpConnector(allow_private=True)


def test_a_slow_server_is_a_structured_timeout(slow_server: str) -> None:
    connector = _connector()
    started = time.monotonic()
    with pytest.raises(ConnectorError) as caught:
        connector.render_and_send(
            url=slow_server,
            body_template='{"question": {{input}}}',
            input_text="hello",
            timeout_seconds=1,
        )
    elapsed = time.monotonic() - started

    assert caught.value.code == "timeout"
    assert caught.value.kind == TIMEOUT
    # It waited for the configured timeout rather than failing instantly on
    # some other error, and it did not wait for the server's two seconds.
    assert 0.8 <= elapsed < 2.0


def test_a_closed_port_is_a_connection_error_not_a_timeout() -> None:
    connector = _connector()
    with pytest.raises(ConnectorError) as caught:
        connector.render_and_send(
            url=f"http://127.0.0.1:{_free_port()}/ask",
            body_template='{"question": {{input}}}',
            input_text="hello",
            timeout_seconds=5,
        )

    assert caught.value.code == "connection_error"
    assert caught.value.kind == CONNECTION


def test_error_kinds_and_codes_stay_in_one_vocabulary() -> None:
    assert kind_for_code("timeout") == TIMEOUT
    assert kind_for_code("connection_error") == CONNECTION
    assert kind_for_code("auth_error") == HTTP_ERROR
    assert kind_for_code("something_new") == OTHER
    assert kind_for_code(None) == OTHER
    assert set(ERROR_KINDS) == {TIMEOUT, CONNECTION, HTTP_ERROR, "invalid_response", OTHER}


class TestOperationsReadsTheKindFirst:
    def test_a_labelled_timeout_counts_even_without_the_word(self) -> None:
        block = compute_operations(
            [ItemSample(state="failed", error="request aborted", error_kind=TIMEOUT)]
        )
        assert block["items_timed_out"] == 1
        assert block["timeout_rate"] == 1.0

    def test_a_labelled_connection_error_does_not_count_as_a_timeout(self) -> None:
        # The message mentions the word, but the connector said it was a refusal.
        block = compute_operations(
            [
                ItemSample(
                    state="failed",
                    error="Could not reach provider: read timeout while connecting",
                    error_kind=CONNECTION,
                )
            ]
        )
        assert block["items_timed_out"] == 0
        assert block["timeout_rate"] == 0.0
        assert block["error_rate"] == 1.0


class TestOldRunFallback:
    def test_old_runs_still_read_the_text(self) -> None:
        block = compute_operations(
            [
                ItemSample(state="failed", error="Request timed out"),
                ItemSample(state="failed", error="Connection refused"),
            ]
        )
        assert block["items_timed_out"] == 1
        assert block["timeout_rate"] == 0.5

    def test_samples_from_items_translates_a_stored_code(self) -> None:
        row = SimpleNamespace(
            state="failed",
            latency_ms=10,
            tokens_in=None,
            tokens_out=None,
            error="increase the timeout or speed up the app",
            trace={"error_code": "timeout", "timed_out": True},
        )

        samples = samples_from_items([row])
        assert samples[0].error_kind == TIMEOUT
        assert compute_operations(samples)["items_timed_out"] == 1

    def test_samples_from_items_prefers_the_stored_kind(self) -> None:
        row = SimpleNamespace(
            state="failed",
            latency_ms=10,
            tokens_in=None,
            tokens_out=None,
            error="could not connect: connection timed out",
            trace={"error_code": "connection_error", "error_kind": CONNECTION},
        )

        assert samples_from_items([row])[0].error_kind == CONNECTION

    def test_a_run_without_any_trace_is_unknown_not_a_timeout(self) -> None:
        row = SimpleNamespace(
            state="failed",
            latency_ms=10,
            tokens_in=None,
            tokens_out=None,
            error="something odd happened",
            trace=None,
        )

        samples = samples_from_items([row])
        assert samples[0].error_kind is None
        assert compute_operations(samples)["items_timed_out"] == 0
