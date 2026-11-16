"""The demo-only control endpoint: loopback, explicit opt-in, fixed mode list.

Every simulator in this folder exposes ``POST /_control/mode`` so a regression
demo can flip its behaviour without a restart. It exists only when the process
was started with ``DEMO_CONTROL=1``, answers 404 otherwise, refuses a client that
is not on loopback, and accepts only the modes the app declares.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from common.web import BadRequest, QuietHandler, read_json, send_error, send_json


def is_loopback(host: str | None) -> bool:
    return host in {"127.0.0.1", "::1"} or bool(host and host.startswith("127."))


def serve_control(
    handler: QuietHandler,
    *,
    enabled: bool,
    modes: tuple[str, ...],
    apply: Callable[[str], None],
) -> None:
    """Answer one control request, or explain in the same JSON shape as the app."""
    if not enabled:
        send_error(handler, 404, "not_found")
        return
    if not is_loopback(handler.client_address[0]):
        send_error(handler, 403, "loopback_only")
        return
    try:
        payload: dict[str, Any] = read_json(handler, 10_000)
    except BadRequest as exc:
        send_error(handler, exc.status, exc.message)
        return
    mode = payload.get("mode")
    if mode not in modes:
        send_error(handler, 400, f"mode must be one of {list(modes)}")
        return
    apply(str(mode))
    send_json(handler, 200, {"mode": mode})
