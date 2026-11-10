"""One controlled app variant, configured by JSON, for the experiment harness.

Usage (from the repository root)::

    python experiments/apps/server.py --config experiments/apps/app_config/app01.json

The config supplies the port and the behaviour; the seed makes the faulty
questions identical on every start. These apps are for local testing only: they
bind 0.0.0.0 so the GreenLit API container reaches them through
``host.docker.internal``, and they must never be exposed to a network.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from behaviour import delay_seconds, handle, http_status, load_faq
from config import AppConfig, ConfigError, load_config

MAX_BODY_BYTES = 64_000


class ExperimentHandler(BaseHTTPRequestHandler):
    """Serve one question at a time; no state, no logging of question text."""

    config: AppConfig
    faq: list[dict[str, Any]]
    server_version = "ExperimentApp/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        """Silence the access log: question text must not be written anywhere."""
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("", "/health", "/healthz"):
            self._send(200, {"ok": True, "app": self.config.id})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send(400, {"error": "a JSON body is required"})
            return
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"error": "invalid JSON"})
            return
        question = ""
        if isinstance(body, dict):
            for key in ("question", "input", "q", "message"):
                value = body.get(key)
                if isinstance(value, str):
                    question = value
                    break
        if not question:
            self._send(400, {"error": "question is required"})
            return
        delay = delay_seconds(self.config)
        if delay:
            import time

            time.sleep(delay)
        status = http_status(self.config, question)
        if status != 200:
            self._send(status, {"error": "internal error"})
            return
        result = handle(self.config, question, self.faq)
        self._send(200, {"answer": result["answer"], "context": result["context"]})


def build_server(config: AppConfig, port: int | None = None) -> ThreadingHTTPServer:
    """A server for one config, on its declared port unless overridden."""
    faq = load_faq()
    handler = type(
        "BoundExperimentHandler",
        (ExperimentHandler,),
        {"config": config, "faq": faq},
    )
    return ThreadingHTTPServer(
        ("0.0.0.0", port if port is not None else config.port), handler
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.environ.get("EXPERIMENT_APP_CONFIG"))
    parser.add_argument(
        "--port", type=int, default=None, help="Override the config's port"
    )
    args = parser.parse_args(argv)
    if not args.config:
        parser.error("--config (or EXPERIMENT_APP_CONFIG) is required")
    try:
        config = load_config(Path(args.config))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    server = build_server(config, args.port)
    host, port = server.server_address[:2]
    print(f"{config.id} listening on http://{host}:{port} (fault={config.fault})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
