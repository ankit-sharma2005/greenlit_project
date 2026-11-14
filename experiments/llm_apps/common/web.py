"""Small HTTP helpers shared by the three HTTP apps.

The apps are test subjects on a loopback port: no framework, no authentication,
one JSON body in and one body out. Everything odd a client can send is answered
with a 4xx and a short JSON message instead of a traceback.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import Settings
from .llm import ProviderUnavailable


class BadRequest(Exception):
    """A request the app refuses before calling the model."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def read_json(handler: BaseHTTPRequestHandler, limit: int) -> dict[str, Any]:
    """Read one JSON object within the body cap, or raise :class:`BadRequest`."""
    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        raise BadRequest("send a JSON object as the request body")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise BadRequest("Content-Length must be a number") from exc
    if length <= 0:
        raise BadRequest("send a JSON object as the request body")
    if length > limit:
        raise BadRequest(f"the body is larger than {limit} bytes", status=400)
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadRequest("the body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise BadRequest("the body must be a JSON object")
    return payload


def question_of(payload: dict[str, Any], limit: int) -> str:
    """The question, capped; anything else is a 400 with a short reason."""
    if "question" not in payload:
        raise BadRequest('the body must hold a "question" string')
    question = payload["question"]
    if not isinstance(question, str):
        raise BadRequest('"question" must be a string')
    if len(question) > limit:
        raise BadRequest(f"the question is longer than {limit} characters")
    return question


def send_json(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> None:
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(encoded)


def send_error(
    handler: BaseHTTPRequestHandler,
    status: int,
    message: str,
    retry_after: str | None = None,
) -> None:
    headers = {"Retry-After": retry_after} if retry_after else None
    send_json(handler, status, {"error": message}, headers)


def send_unavailable(handler: BaseHTTPRequestHandler, exc: ProviderUnavailable) -> None:
    """A provider failure is the app's 503, never a 500 or a hang."""
    send_error(handler, 503, "provider_unavailable", exc.retry_after)


def health_body(app: str, settings: Settings) -> dict[str, str]:
    return {"status": "ok", "app": app, **settings.public()}


class AppServer(ThreadingHTTPServer):
    """A server that carries the settings and the app's name for /health."""

    settings: Settings
    app_name: str


class QuietHandler(BaseHTTPRequestHandler):
    """A handler whose access log is silent: the app writes its own JSONL line."""

    server_version = "GreenLitLLMTestApp/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/health":
            settings = getattr(self.server, "settings", None)
            app = getattr(self.server, "app_name", "unknown")
            if settings is None:
                send_error(self, 500, "server settings are missing")
                return
            send_json(self, 200, health_body(app, settings))
            return
        send_error(self, 404, "not_found")
