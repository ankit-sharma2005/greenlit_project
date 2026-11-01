"""Streamed target answers: SSE, NDJSON and plain text, joined and bounded.

A real company chatbot streams its answer. These tests run real local servers
that stream in each supported shape, stall, or never stop talking, and check
what the shared request function records.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest

from app.services.connectors import MAX_ANSWER_BYTES, ConnectorError, HttpConnector


def _sse_openai() -> list[bytes]:
    events = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "Hello"}}]},
        {"choices": [{"delta": {"content": " world"}}]},
    ]
    chunks = [f"data: {json.dumps(event)}\n\n".encode() for event in events]
    chunks.append(b"data: [DONE]\n\n")
    return chunks


def _sse_plain() -> list[bytes]:
    return [b": keepalive\n\n", b"data: Hello\n\n", b"data:  world\n\n"]


def _ndjson() -> list[bytes]:
    return [b'{"token": "Hello"}\n', b'{"token": " world"}\n']


def _oversized() -> list[bytes]:
    # Each event carries 4 KB, so the cap is crossed after ~26 events.
    piece = "x" * 4096
    return [f'{{"token": "{piece}"}}\n'.encode() for _ in range(40)]


class _Handler(BaseHTTPRequestHandler):
    mode: ClassVar[str] = "sse_openai"
    chunks: ClassVar[list[bytes]] = []
    pause_before_first: ClassVar[float] = 0.0
    stall_after_first: ClassVar[float] = 0.0

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if type(self).pause_before_first:
                time.sleep(type(self).pause_before_first)
            for index, chunk in enumerate(type(self).chunks):
                self.wfile.write(chunk)
                self.wfile.flush()
                if index == 0 and type(self).stall_after_first:
                    time.sleep(type(self).stall_after_first)
            self.close_connection = True
        except OSError:
            # The client stopped reading (timeout or size cap), as intended.
            return

    def log_message(self, *args: object) -> None:
        return


def _make_server(
    mode: str,
    *,
    pause_before_first: float = 0.0,
    stall_after_first: float = 0.0,
) -> tuple[ThreadingHTTPServer, str]:
    chunks = {
        "sse_openai": _sse_openai,
        "sse_plain": _sse_plain,
        "ndjson": _ndjson,
        "text": lambda: [b"Hello", b" world"],
        "oversized": _oversized,
        "stall": lambda: [b"data: partial\n\n"],
    }[mode]()
    handler: Any = type(f"Handler_{mode}", (_Handler,), {})
    handler.mode = mode
    handler.chunks = chunks
    handler.pause_before_first = pause_before_first
    handler.stall_after_first = stall_after_first
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/chat"


@pytest.fixture
def serve() -> Iterator[Any]:
    servers: list[ThreadingHTTPServer] = []

    def start(mode: str, **kwargs: float) -> str:
        httpd, url = _make_server(mode, **kwargs)
        servers.append(httpd)
        return url

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def _connector() -> HttpConnector:
    return HttpConnector(allow_private=True, min_delay_ms=0, max_retries=0)


def _send(url: str, response_format: str, path: str | None = None) -> Any:
    return _connector().render_and_send(
        url=url,
        body_template='{"question": {{input}}}',
        input_text="hello",
        timeout_seconds=5,
        response_format=response_format,
        stream_content_path=path,
    )


def test_sse_openai_delta_is_joined(serve: Any) -> None:
    trace = _send(serve("sse_openai"), "sse")
    assert trace.output == "Hello world"
    assert trace.time_to_first_byte_ms is not None
    assert trace.latency_ms >= trace.time_to_first_byte_ms


def test_sse_plain_data_and_keepalive_are_understood(serve: Any) -> None:
    # No JSON path: the plain data: fallback joins the text, comments ignored.
    assert _send(serve("sse_plain"), "sse").output == "Hello world"


def test_sse_explicit_path_wins(serve: Any) -> None:
    trace = _send(serve("sse_openai"), "sse", "choices.0.delta.content")
    assert trace.output == "Hello world"


def test_ndjson_token_lines_are_joined(serve: Any) -> None:
    trace = _send(serve("ndjson"), "ndjson")
    assert trace.output == "Hello world"
    assert trace.raw["response_format"] == "ndjson"


def test_plain_text_stream_is_the_answer(serve: Any) -> None:
    assert _send(serve("text"), "text").output == "Hello world"


def test_a_stalled_stream_times_out_cleanly(serve: Any) -> None:
    url = serve("stall", stall_after_first=5.0)
    started = time.monotonic()
    with pytest.raises(ConnectorError) as caught:
        _connector().render_and_send(
            url=url,
            body_template='{"question": {{input}}}',
            input_text="hello",
            timeout_seconds=1,
            response_format="sse",
        )
    elapsed = time.monotonic() - started
    assert caught.value.code == "timeout"
    assert elapsed < 4.0


def test_an_oversized_stream_is_cut_with_a_clear_error(serve: Any) -> None:
    with pytest.raises(ConnectorError) as caught:
        _send(serve("oversized"), "ndjson")
    assert caught.value.code == "response_too_large"
    assert f"{MAX_ANSWER_BYTES // 1024} KB" in caught.value.message


def test_first_byte_is_measured_before_a_paused_answer(serve: Any) -> None:
    trace = _send(serve("sse_openai", pause_before_first=0.3), "sse")
    assert trace.output == "Hello world"
    assert trace.time_to_first_byte_ms is not None
    assert trace.time_to_first_byte_ms >= 250
