"""One local server that refuses requests the way real sites do.

Every mode is a status, a set of response headers and a body. The tests point
the real connector at it, so what is asserted is the message a person reads and
the structured detail the report stores — never a mock of the classifier.
"""

from __future__ import annotations

import argparse
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


@dataclass
class Refusal:
    """One scripted answer: the status, headers and body a site sends back."""

    status: int
    headers: dict[str, str]
    body: str


CLOUDFLARE_CHALLENGE = Refusal(
    403,
    {
        "Content-Type": "text/html; charset=UTF-8",
        "Server": "cloudflare",
        "CF-RAY": "8f2a1c4d0e7b1234-LHR",
        "cf-mitigated": "challenge",
    },
    "<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>"
    "<h1>Verify you are human</h1><p>Checking your browser before accessing.</p>"
    "</body></html>",
)

# A plain web server's own 403: no challenge, no CDN, just a refused path.
NGINX_FORBIDDEN = Refusal(
    403,
    {"Content-Type": "text/html", "Server": "nginx/1.25.3"},
    "<html><head><title>403 Forbidden</title></head><body>"
    "<center><h1>403 Forbidden</h1></center><hr><center>nginx/1.25.3</center>"
    "</body></html>",
)

# Django/Rails-style refusal: JSON, and the reason is a stale anti-forgery token.
CSRF_JSON = Refusal(
    403,
    {"Content-Type": "application/json", "Server": "gunicorn"},
    json.dumps({"detail": "CSRF token missing."}),
)

# A CDN that blocks automation but answers JSON (no challenge HTML at all).
AKAMAI_DENIED = Refusal(
    403,
    {
        "Content-Type": "application/json",
        "Server": "AkamaiGHost",
        "X-Akamai-Request-ID": "1a2b3c4d",
    },
    json.dumps({"errors": [{"title": "Access Denied", "detail": "Reference #18.5f2f1402"}]}),
)

# What a site sends when the pasted session has expired: its login page.
LOGIN_PAGE = Refusal(
    401,
    {"Content-Type": "text/html; charset=utf-8", "Server": "werkzeug"},
    "<!DOCTYPE html><html><head><title>Sign in</title></head><body>"
    '<form action="/login" method="post"><input name="email"></form></body></html>',
)

BEARER_401 = Refusal(
    401,
    {
        "Content-Type": "application/json",
        "WWW-Authenticate": 'Bearer realm="api", error="invalid_token"',
    },
    json.dumps({"error": "invalid_token", "detail": "token expired"}),
)

PERMISSION_403 = Refusal(
    403,
    {"Content-Type": "application/json"},
    json.dumps({"error": "forbidden", "detail": "no access to this workspace"}),
)

RATE_LIMITED = Refusal(
    429,
    {"Content-Type": "application/json", "Retry-After": "0"},
    json.dumps({"error": "rate limited"}),
)

MODES: dict[str, Refusal] = {
    "cloudflare_challenge": CLOUDFLARE_CHALLENGE,
    "nginx_forbidden": NGINX_FORBIDDEN,
    "csrf_json": CSRF_JSON,
    "akamai_denied": AKAMAI_DENIED,
    "login_page": LOGIN_PAGE,
    "bearer_401": BEARER_401,
    "permission_403": PERMISSION_403,
    "rate_limited": RATE_LIMITED,
}


@dataclass
class RefusalServer:
    """A running server plus what it received, so a test can prove call counts."""

    httpd: ThreadingHTTPServer
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/chat"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def start_refusal(mode: str) -> RefusalServer:
    """Start a loopback server answering ``mode`` until it is closed."""
    refusal = MODES[mode]
    server = RefusalServer(httpd=None)  # type: ignore[arg-type]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            self.rfile.read(length) if length else None
            server.calls.append(dict(self.headers.items()))
            payload = refusal.body.encode("utf-8")
            # Not ``send_response``: that adds the stdlib's own Server and Date
            # headers, and the test reads the CDN's Server header verbatim.
            self.send_response_only(refusal.status)
            for name, value in refusal.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            """Keep the test output readable."""

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    server.httpd = httpd
    return server


def _mode_handler(counts: dict[str, int]) -> type[BaseHTTPRequestHandler]:
    """Every mode on one server, addressed by path, counting what was asked for.

    ``POST /<mode>`` answers that refusal. ``GET /_calls`` reports the counts, so
    a browser test can prove a challenge was requested exactly once instead of
    trusting the page. ``GET /_health`` is the harness's readiness probe.
    """

    class ModeHandler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response_only(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/_health":
                self._json(200, {"ok": True, "modes": sorted(MODES)})
            elif self.path == "/_calls":
                self._json(200, dict(counts))
            else:
                self._json(404, {"error": "unknown path"})

        def do_POST(self) -> None:
            parts = [part for part in self.path.strip("/").split("/") if part]
            first_ok = bool(parts) and parts[0] == "first-ok"
            mode = parts[1] if first_ok and len(parts) > 1 else (parts[0] if parts else "")
            refusal = MODES.get(mode)
            if refusal is None:
                self._json(404, {"error": f"unknown refusal mode {mode!r}"})
                return
            length = int(self.headers.get("content-length") or 0)
            if length:
                self.rfile.read(length)
            already = counts.get(mode, 0)
            counts[mode] = already + 1
            if first_ok and already == 0:
                # The UI shows the check panel only after a successful first
                # contact, so the browser's auto-detect gets one readable 200
                # and every request after it gets the real refusal.
                body = json.dumps({"answer": "ok"}).encode("utf-8")
                self.send_response_only(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            payload = refusal.body.encode("utf-8")
            # As above: the CDN's own Server header, not the stdlib's.
            self.send_response_only(refusal.status)
            for name, value in refusal.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: Any) -> None:
            """Keep the harness log readable."""

    return ModeHandler


def serve(port: int = 9503, host: str = "127.0.0.1") -> None:
    """Run the refusal server for the browser suite until interrupted."""
    counts: dict[str, int] = {}
    httpd = ThreadingHTTPServer((host, port), _mode_handler(counts))
    httpd.daemon_threads = True
    print(f"refusal server on http://{host}:{port} ({len(MODES)} modes)", flush=True)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refusal server for the browser suite.")
    parser.add_argument("--port", type=int, default=9503)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    serve(port=args.port, host=args.host)
