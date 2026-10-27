"""Liveness and readiness endpoints."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal

logger = logging.getLogger("greenlit.health")

router = APIRouter(tags=["health"])


def check_database() -> None:
    """Raise when Postgres cannot answer a trivial query."""
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))


def check_redis() -> None:
    """Raise when Redis cannot answer PING."""
    # redis-py 5.x annotates Redis.from_url as returning None even though it
    # returns a client, so the value is typed Any here — the same convention the
    # rate limiter and the progress reporter use. Without it mypy strict rejects
    # the .ping() below with "None has no attribute ping".
    client: Any = redis.Redis.from_url(
        get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2
    )
    try:
        client.ping()
    finally:
        client.close()


@router.get("/healthz", summary="Liveness probe")
def healthz() -> dict[str, str]:
    """Return 200 while the process is serving requests (no dependencies checked)."""
    return {"status": "ok", "service": "greenlit-api"}


@router.get("/readyz", summary="Readiness probe", response_model=None)
def readyz() -> JSONResponse | dict[str, Any]:
    """Report dependency readiness; 503 when any dependency is unreachable."""
    checks: dict[str, str] = {}
    ok = True
    for name, check in _readiness_checks():
        try:
            check()
            checks[name] = "ok"
        except Exception:
            logger.warning("Readiness check failed: %s", name, exc_info=True)
            checks[name] = "unreachable"
            ok = False
    body: dict[str, Any] = {"status": "ready" if ok else "not_ready", "checks": checks}
    if not ok:
        return JSONResponse(status_code=503, content=body)
    return body


def _readiness_checks() -> list[tuple[str, Callable[[], None]]]:
    return [("database", check_database), ("redis", check_redis)]
