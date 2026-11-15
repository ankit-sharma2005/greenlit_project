"""A tiny stand-in for one catalog app, for the e2e catalog spec.

It answers ``GET /health`` with the same fields the real support bot answers, so
the e2e stack can prove the up state without the real port 9111. It is started by
``scripts/run-e2e.sh`` only.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class Handler(BaseHTTPRequestHandler):
    app_name = "support-bot"
    mode = "guarded"

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/health":
            self._send(
                200,
                {
                    "status": "ok",
                    "app": self.app_name,
                    "mode": self.mode,
                    "provider": "none",
                    "model": "none",
                },
            )
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        self._send(404, {"error": "not_found"})

    def log_message(self, format: str, *args: object) -> None:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Catalog health stand-in")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"demo stand-in on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
