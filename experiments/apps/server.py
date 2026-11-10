"""One controlled app variant, configured by JSON, for the experiment harness.

Usage (from the repository root)::

    python experiments/apps/server.py --config experiments/apps/app_config/app01.json

The config supplies the port and the behaviour; the seed makes the faulty
questions identical on every start. These apps are for local testing only: they
bind 0.0.0.0 so the GreenLit API container reaches them through
``host.docker.internal``, and they must never be exposed to a network.

Each request also appends one line to ``results/app_logs/<app id>.jsonl``: the
question, whether the app's own seeded fault fired, and the answer it returned.
That file is the app's own record of truth, it stays on this machine (``results/``
is git-ignored), and GreenLit never sees it — the access log itself stays silent.
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
APP_LOGS = Path(__file__).resolve().parent.parent / "results" / "app_logs"


def append_log(
    config: AppConfig,
    question: str,
    result: dict[str, Any],
    log_dir: Path | None = None,
) -> Path:
    """One JSON line per request: the question, the fault flag, the answer.

    Nothing else is recorded, so the file can be read back without a token, a
    header or an identifier in it. The caller decides where it goes; the default
    is the git-ignored ``results/app_logs``.
    """
    directory = APP_LOGS if log_dir is None else log_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{config.id}.jsonl"
    line = {
        "question": question,
        "faulted": bool(result.get("faulted")),
        "answer": result.get("answer"),
    }
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


class ExperimentHandler(BaseHTTPRequestHandler):
    """Serve one question at a time; no state, and no access log at all."""

    config: AppConfig
    faq: list[dict[str, Any]]
    log_dir: Path | None = None
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
        try:
            append_log(self.config, question, result, self.log_dir)
        except OSError:
            # A full disk must not turn a good answer into a failed case; the
            # analysis says so plainly when the log is missing.
            pass
        self._send(200, {"answer": result["answer"], "context": result["context"]})


def build_server(
    config: AppConfig, port: int | None = None, log_dir: Path | None = None
) -> ThreadingHTTPServer:
    """A server for one config, on its declared port unless overridden."""
    faq = load_faq()
    handler = type(
        "BoundExperimentHandler",
        (ExperimentHandler,),
        {"config": config, "faq": faq, "log_dir": log_dir},
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
