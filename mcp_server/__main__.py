"""stdio entry point: ``python -m mcp_server``.

Configuration comes only from the environment: ``GREENLIT_URL`` (default
``http://localhost:8003``), ``GREENLIT_EMAIL``, ``GREENLIT_PASSWORD`` and, to
enable the write tool, ``GREENLIT_MCP_ALLOW_START=1``. The credentials are never
printed; a missing one is reported by name only.
"""

from __future__ import annotations

import os
import sys

from mcp_server.client import GreenLitClient, GreenLitError
from mcp_server.server import build_server


def main() -> int:
    email = os.environ.get("GREENLIT_EMAIL", "")
    password = os.environ.get("GREENLIT_PASSWORD", "")
    if not email or not password:
        missing = [
            name
            for name, value in (
                ("GREENLIT_EMAIL", email),
                ("GREENLIT_PASSWORD", password),
            )
            if not value
        ]
        print(
            f"Set {' and '.join(missing)} so the server can sign in to GreenLit.",
            file=sys.stderr,
        )
        return 2

    base_url = os.environ.get("GREENLIT_URL", "http://localhost:8003")
    try:
        client = GreenLitClient(base_url, email, password)
    except GreenLitError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    allow_start = os.environ.get("GREENLIT_MCP_ALLOW_START", "").strip() == "1"
    build_server(client, allow_start=allow_start).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
