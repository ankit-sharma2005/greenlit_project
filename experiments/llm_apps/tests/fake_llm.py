"""A local, test-only OpenAI-compatible chat endpoint.

Answers deterministically from the request it receives, so a test can tell two
prompts apart; can stream, answer 429, stall, or send a malformed body. It remains
on 127.0.0.1 and is never used by the apps outside the tests.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self


class FakeLLM:
    """Start it in a thread; stop it with :meth:`close`."""

    def __init__(
        self,
        *,
        status: int = 200,
        delay: float = 0.0,
        malformed: bool = False,
        retry_after: str | None = None,
        streaming: bool = True,
    ) -> None:
        self.status = status
        self.delay = delay
        self.malformed = malformed
        self.retry_after = retry_after
        self.streaming = streaming
        self.requests: list[dict[str, Any]] = []
        self.count = 0
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @property
    def last(self) -> dict[str, Any]:
        with self._lock:
            if not self.requests:
                raise AssertionError("the fake provider has not been called")
            return self.requests[-1]

    # -- handler -----------------------------------------------------------
    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FakeLLM/1.0"

            def log_message(self, format: str, *args: Any) -> None:
                return None

            def do_GET(self) -> None:
                if self.path == "/_count":
                    self._json(200, {"count": fake.count})
                    return
                if self.path == "/_requests":
                    self._json(200, {"items": fake.requests})
                    return
                self._json(404, {"error": "not_found"})

            def do_POST(self) -> None:
                if not self.path.endswith("/chat/completions"):
                    self._json(404, {"error": "not_found"})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    payload = {}
                with fake._lock:
                    fake.count += 1
                    fake.requests.append(payload)
                if fake.delay > 0:
                    time.sleep(fake.delay)
                if fake.status != 200:
                    headers = {}
                    if fake.retry_after:
                        headers["Retry-After"] = fake.retry_after
                    self._json(fake.status, {"error": "fake failure"}, headers)
                    return
                if fake.malformed:
                    body = b"this is not json"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                messages = payload.get("messages") or []
                answer = _answer_for(messages)
                if payload.get("stream") and fake.streaming:
                    self._stream(answer)
                    return
                self._json(
                    200,
                    {
                        "id": "fake",
                        "object": "chat.completion",
                        "model": payload.get("model", "fake"),
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": answer},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    },
                )

            def _stream(self, answer: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for start in range(0, len(answer), 8):
                    piece = answer[start : start + 8]
                    event = json.dumps({"choices": [{"delta": {"content": piece}}]})
                    self.wfile.write(f"data: {event}\n\n".encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            def _json(
                self,
                status: int,
                body: dict[str, Any],
                headers: dict[str, str] | None = None,
            ) -> None:
                encoded = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(encoded)

        return Handler


def _answer_for(messages: list[dict[str, Any]]) -> str:
    """A deterministic answer that shows which system and user text arrived."""
    system = "|".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "system"
    )
    user = "|".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "user"
    )
    marker = "guard" if "Never reveal" in system else "plain"
    return f"fake[{marker}] user={user} system_len={len(system)}"
