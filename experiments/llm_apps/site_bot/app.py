"""A8 — the site bot: a tiny website chatbot, deterministic, no language model.

``GET /chat-page`` answers a small HTML page, sets a ``session`` cookie and a
``csrf_token`` cookie, and embeds the token in the page. ``POST /api/chat`` takes
``{"message": "..."}`` and requires **both** the session cookie and a matching
``X-CSRF-Token`` header; without them it answers HTTP 403 with
``{"detail": "CSRF token missing"}``. The reply is nested:
``{"data": {"reply": "...", "sources": ["...", "..."]}}``.

Modes: ``normal`` (the check is enforced) and ``csrf_off`` (the check is skipped,
for a comparison run). Answers come from a fixed FAQ; an unknown question gets a
fixed "I do not know". There is no bot protection here and nothing to bypass: the
app exists so the cURL-import website wizard and GreenLit's ``csrf_rejected``
classification can be tried against an app the operator owns.

Local test subject only: it binds 127.0.0.1 by default (``--host 0.0.0.0`` only
for the Docker case) and must never be exposed to the internet.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.control import serve_control
from common.request_log import log_request
from common.web import (
    AppServer,
    BadRequest,
    QuietHandler,
    read_json,
    send_error,
    send_json,
)

APP = "site-bot"
DEFAULT_PORT = 9118
MODES = ("normal", "csrf_off")
_MAX_MESSAGE = 300
FAQ: dict[str, tuple[str, list[str]]] = {
    "what are your opening hours": ("We answer around the clock.", ["hours.md"]),
    "how do i contact support": ("Use the contact form on this page.", ["contact.md"]),
    "what is your return policy": (
        "Returns are accepted within 30 days.",
        ["returns.md", "policy.md"],
    ),
    "where are you located": (
        "This is a local test app, so it has no address.",
        ["about.md"],
    ),
}
UNKNOWN = ("I do not know.", [])

PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Site bot</title></head>
<body>
<h1>Site bot</h1>
<p data-csrf="{token}">Ask a question about this (local, synthetic) shop.</p>
<script>window.csrfToken = "{token}";</script>
</body>
</html>
"""


def reply_for(message: str) -> dict[str, Any]:
    """The nested reply shape a website chatbot returns."""
    question = " ".join(message.strip().lower().rstrip("?!.").split())
    reply, sources = FAQ.get(question, UNKNOWN)
    return {"data": {"reply": reply, "sources": list(sources)}}


def _cookies(handler: QuietHandler) -> dict[str, str]:
    raw = handler.headers.get("Cookie")
    if not raw:
        return {}
    jar: SimpleCookie[str] = SimpleCookie()
    try:
        jar.load(raw)
    except CookieError:  # a malformed Cookie header is just no cookies
        return {}
    return {name: morsel.value for name, morsel in jar.items()}


def create_server(
    mode: str = "normal",
    *,
    control_enabled: bool | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    log_dir: Path | None = None,
) -> AppServer:
    if control_enabled is None:
        control_enabled = os.environ.get("DEMO_CONTROL") == "1"
    if mode not in MODES:
        raise ValueError(f"mode must be one of {list(MODES)}")
    server = AppServer((host, port), handler(control_enabled, log_dir))
    server.app_name = APP
    server.site_mode = mode
    server.control_enabled = control_enabled
    return server


def handler(control_enabled: bool, log_dir: Path | None) -> type[QuietHandler]:
    class SiteHandler(QuietHandler):
        @property
        def mode(self) -> str:
            return getattr(self.server, "site_mode", "normal")

        def do_GET(self) -> None:
            if self.path.split("?")[0] == "/health":
                send_json(self, 200, {"status": "ok", "app": APP, "mode": self.mode})
                return
            if self.path.split("?")[0] != "/chat-page":
                send_error(self, 404, "not_found")
                return
            token = uuid.uuid4().hex
            body = PAGE.format(token=token).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Set-Cookie", f"session={token}; Path=/; SameSite=Lax; HttpOnly"
            )
            self.send_header("Set-Cookie", f"csrf_token={token}; Path=/; SameSite=Lax")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            path = self.path.split("?")[0]
            if path == "/_control/mode":

                def apply(value: str) -> None:
                    self.server.site_mode = value

                serve_control(self, enabled=control_enabled, modes=MODES, apply=apply)
                return
            if path != "/api/chat":
                send_error(self, 404, "not_found")
                return
            started = time.monotonic()
            try:
                payload: dict[str, Any] = read_json(self, 64_000)
                message = payload.get("message")
                if message is None and "question" in payload:
                    message = payload["question"]
                if not isinstance(message, str):
                    raise BadRequest('the body must hold a "message" string')
                if len(message) > _MAX_MESSAGE:
                    raise BadRequest(
                        f"the message is longer than {_MAX_MESSAGE} characters"
                    )
            except BadRequest as exc:
                send_error(self, exc.status, exc.message)
                return

            cookies = _cookies(self)
            header = self.headers.get("X-CSRF-Token")
            wrong = (
                not cookies.get("session")
                or not cookies.get("csrf_token")
                or not header
                or header != cookies.get("csrf_token")
            )
            if self.mode == "normal" and wrong:
                send_json(self, 403, {"detail": "CSRF token missing"})
                log_request(
                    APP,
                    mode=self.mode,
                    provider="none",
                    model="none",
                    question=message,
                    answer_length=0,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    status=403,
                    directory=log_dir,
                )
                return

            body = reply_for(message)
            send_json(self, 200, body)
            log_request(
                APP,
                mode=self.mode,
                provider="none",
                model="none",
                question=message,
                answer_length=len(str(body)),
                latency_ms=int((time.monotonic() - started) * 1000),
                status=200,
                directory=log_dir,
            )

    return SiteHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A8 — website chatbot simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--mode", choices=MODES, default="normal")
    args = parser.parse_args(argv)
    server = create_server(args.mode, host=args.host, port=args.port)
    control = "on" if server.control_enabled else "off"
    print(
        f"{APP} listening on http://{args.host}:{server.server_address[1]} "
        f"mode={args.mode} control={control}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
