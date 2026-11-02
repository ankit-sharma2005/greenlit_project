"""One configurable local server that mimics how real apps misbehave.

Every quirk is a ``mode`` on a loopback ``ThreadingHTTPServer``; the tests point
the real connector at it. Nothing here talks to the internet, and every mode
records what it was sent (path, headers, call count) so a test can prove what
did **not** happen — for example that a cross-host redirect was never followed.
"""

from __future__ import annotations

import gzip
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ANSWER = "Hello from the quirk server"


@dataclass
class QuirkServer:
    """A running quirk server plus the record of what it received."""

    mode: str
    httpd: ThreadingHTTPServer
    seen: list[str] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)
    calls: int = 0
    expire_after: int = 1
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def base(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def url(self) -> str:
        return f"{self.base}/chat"

    def paths_seen(self) -> list[str]:
        with self.lock:
            return list(self.seen)

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload).encode("utf-8")


def start_quirk(mode: str, *, expire_after: int = 1) -> QuirkServer:
    """Start a quirk server on a free loopback port."""

    def answer() -> tuple[int, dict[str, str], bytes]:
        return 200, {"Content-Type": "application/json"}, _json_bytes({"answer": ANSWER})

    def html(status: int, body: str) -> tuple[int, dict[str, str], bytes]:
        return status, {"Content-Type": "text/html; charset=utf-8"}, body.encode()

    def redirect(location: str) -> tuple[int, dict[str, str], bytes]:
        return 302, {"Location": location}, b""

    def shaped() -> tuple[int, dict[str, str], bytes]:
        if mode == "openai":
            payload: Any = {"choices": [{"message": {"content": ANSWER}}]}
        elif mode == "nested":
            payload = {"data": {"result": {"answer": ANSWER}}}
        elif mode == "messages_array":
            payload = [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": ANSWER},
            ]
        elif mode == "null_answer":
            payload = {"answer": None}
        elif mode == "plain_text":
            return 200, {"Content-Type": "text/plain"}, ANSWER.encode()
        elif mode == "empty":
            return 200, {"Content-Type": "application/json"}, b""
        elif mode == "html_200":
            return html(200, "<html><body>Internal error page</body></html>")
        elif mode == "invalid_utf8":
            return 200, {"Content-Type": "application/json"}, b'{"answer": "\xff\xfe broken"}'
        elif mode == "gzip":
            body = gzip.compress(_json_bytes({"answer": ANSWER}))
            return 200, {"Content-Type": "application/json", "Content-Encoding": "gzip"}, body
        elif mode == "huge":
            body = _json_bytes({"answer": "x" * (10 * 1024 * 1024 + 1024)})
            return 200, {"Content-Type": "application/json"}, body
        else:
            return answer()
        return 200, {"Content-Type": "application/json"}, _json_bytes(payload)

    server = QuirkServer(mode=mode, httpd=None, expire_after=expire_after)  # type: ignore[arg-type]

    class Handler(BaseHTTPRequestHandler):
        def _record(self) -> None:
            with server.lock:
                server.calls += 1
                server.seen.append(self.path)
                server.headers.append(dict(self.headers.items()))

        def _respond(self, status: int, headers: dict[str, str], body: bytes) -> None:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            self._record()

            if mode == "auth_bearer":
                if self.headers.get("Authorization") != "Bearer test-token":
                    self._respond(401, {"Content-Type": "application/json"}, b"{}")
                    return
                self._respond(*answer())
                return
            if mode == "auth_api_key":
                if self.headers.get("X-Api-Key") != "test-key":
                    self._respond(401, {"Content-Type": "application/json"}, b"{}")
                    return
                self._respond(*answer())
                return
            if mode == "auth_basic":
                if self.headers.get("Authorization") != "Basic ZGVtbzpkZW1v":
                    self._respond(401, {"Content-Type": "application/json"}, b"{}")
                    return
                self._respond(*answer())
                return
            if mode == "auth_cookie":
                if "session=abc" not in (self.headers.get("Cookie") or ""):
                    self._respond(401, {"Content-Type": "application/json"}, b"{}")
                    return
                self._respond(*answer())
                return
            if mode == "expire" and server.calls > server.expire_after:
                self._respond(
                    401,
                    {"Content-Type": "application/json"},
                    _json_bytes({"error": "token expired"}),
                )
                return
            if mode == "challenge":
                self._respond(
                    *html(
                        403,
                        "<html><head><title>Just a moment...</title></head><body>"
                        "<h1>Verify you are human</h1>"
                        "<p>Checking your browser before accessing.</p></body></html>",
                    )
                )
                return
            if mode == "redirect_same" and self.path == "/chat":
                self._respond(*redirect("/chat-next"))
                return
            if mode == "redirect_loop":
                self._respond(*redirect("/loop"))
                return
            if mode == "redirect_other_host" and self.path == "/chat":
                host = self.headers.get("Host") or ""
                self._respond(*redirect(f"http://localhost:{host.split(':')[-1]}/elsewhere"))
                return
            if mode == "stream_sse":
                self._stream_sse(final_event=True)
                return
            if mode == "stream_no_done":
                self._stream_sse(final_event=False)
                return
            if mode == "stream_stall":
                self._stream_stall()
                return
            self._respond(*shaped())

        def _stream_sse(self, *, final_event: bool) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                for piece in ("Hello", " from", " the stream"):
                    event = json.dumps({"choices": [{"delta": {"content": piece}}]})
                    self.wfile.write(f"data: {event}\n\n".encode())
                    self.wfile.flush()
                if final_event:
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
            except OSError:
                return
            self.close_connection = True

        def _stream_stall(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                self.wfile.write(b'data: {"token": "partial"}\n\n')
                self.wfile.flush()
                # Never finish: the client's read timeout has to end this.
                threading.Event().wait(30)
            except OSError:
                return

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def log_message(self, format: str, *args: object) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    server.httpd = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return server


def quirk(mode: str, **kwargs: Any) -> Iterator[QuirkServer]:
    """Pytest fixture helper: start a quirk server and stop it afterwards."""
    server = start_quirk(mode, **kwargs)
    try:
        yield server
    finally:
        server.close()
