from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.api import health
from app.main import app


def _passing_checks() -> list[tuple[str, Callable[[], None]]]:
    return [("database", lambda: None), ("redis", lambda: None)]


def test_healthz_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "greenlit-api"}


def test_root_points_at_docs() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_readyz_reports_ready(monkeypatch) -> None:
    monkeypatch.setattr(health, "_readiness_checks", _passing_checks)

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok"},
    }


def test_readyz_reports_unreachable_dependency(monkeypatch) -> None:
    def broken() -> None:
        raise RuntimeError("connection refused")

    def checks() -> list[tuple[str, Callable[[], None]]]:
        return [("database", lambda: None), ("redis", broken)]

    monkeypatch.setattr(health, "_readiness_checks", checks)

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {"database": "ok", "redis": "unreachable"}
