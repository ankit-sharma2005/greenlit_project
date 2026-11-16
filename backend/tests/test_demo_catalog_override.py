"""The test-only catalog probe override, and the fenced door around it.

It exists so the e2e stack can point the five fixed catalog entries at stand-in
servers. These tests prove the fence: no flag means no effect, only known entries
and only scheme/host/port change, it is read at import and never from a request,
and every probe still happens on the catalog's own path with GET.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services import demo_catalog

PASSWORD = "correct horse battery staple"


def _register(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "ada@example.com", "name": "Ada", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def test_without_the_e2e_flag_the_override_is_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = {"DEMO_CATALOG_PROBE_ORIGINS": "support-bot=http://127.0.0.1:9505"}
    with caplog.at_level(logging.WARNING, logger=demo_catalog.__name__):
        assert demo_catalog.read_probe_origins(env) == {}
    assert "GREENLIT_E2E" in caplog.text


def test_with_the_flag_it_accepts_known_entries_only() -> None:
    env = {
        "GREENLIT_E2E": "1",
        "DEMO_CATALOG_PROBE_ORIGINS": (
            "support-bot=http://127.0.0.1:9505, not-an-app=http://evil.test,"
            "math-solver=file:///etc/passwd"
        ),
    }
    origins = demo_catalog.read_probe_origins(env)
    assert origins == {"support-bot": "http://127.0.0.1:9505"}


def test_an_empty_override_is_no_override() -> None:
    assert demo_catalog.read_probe_origins({"GREENLIT_E2E": "1"}) == {}


def test_the_override_changes_only_the_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        demo_catalog,
        "PROBE_ORIGINS",
        {"support-bot": "http://127.0.0.1:9505", "stream-bot": "http://127.0.0.1:9506"},
    )
    by_id = {entry.id: entry for entry in demo_catalog.CATALOG}
    assert demo_catalog.probe_url(by_id["support-bot"]) == "http://127.0.0.1:9505/health"
    # The catalog's own path is kept; only scheme, host and port change.
    assert demo_catalog.probe_url(by_id["stream-bot"]) == "http://127.0.0.1:9506/sse/health"
    assert demo_catalog.probe_url(by_id["math-solver"]) == (
        "http://host.docker.internal:9115/health"
    )


def test_the_environment_is_read_at_start_not_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = dict(demo_catalog.PROBE_ORIGINS)
    monkeypatch.setenv("GREENLIT_E2E", "1")
    monkeypatch.setenv("DEMO_CATALOG_PROBE_ORIGINS", "support-bot=http://127.0.0.1:9505")
    assert before == demo_catalog.PROBE_ORIGINS


def test_no_request_can_choose_the_probed_address(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(client)
    monkeypatch.setattr(demo_catalog, "PROBE_ORIGINS", {"support-bot": "http://127.0.0.1:9505"})
    probed: list[str] = []

    class FakeResponse:
        status = 200

        def read(self, _limit: int) -> bytes:
            return json.dumps({"status": "ok", "app": "stand-in", "mode": "correct"}).encode()

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class FakeOpener:
        def open(self, url: str, timeout: float) -> FakeResponse:
            del timeout
            probed.append(url)
            return FakeResponse()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_handlers: FakeOpener())
    response = client.get(
        "/api/v1/demo-apps",
        params={"url": "http://169.254.169.254/latest", "host": "10.0.0.1"},
        headers={
            "X-Demo-Origin": "http://evil.test",
            "X-Demo-Catalog-Probe-Origins": "support-bot=http://evil.test",
        },
    )
    assert response.status_code == 200, response.text
    # Eight probes, all on the catalog's own paths, with only the support-bot origin
    # replaced by the startup value — nothing from the request appears in a URL.
    assert probed == [
        "http://127.0.0.1:9505/health",
        "http://host.docker.internal:9112/health",
        "http://host.docker.internal:9113/sse/health",
        "http://host.docker.internal:9114/mcp/health",
        "http://host.docker.internal:9115/health",
        "http://host.docker.internal:9116/health",
        "http://host.docker.internal:9117/health",
        "http://host.docker.internal:9118/api/chat/health",
    ]
    assert not any("evil.test" in url or "169.254" in url for url in probed)
    assert demo_catalog.PROBE_ORIGINS == {"support-bot": "http://127.0.0.1:9505"}


def test_the_override_is_never_read_from_os_environ_at_request_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register(client)
    monkeypatch.setattr(demo_catalog, "PROBE_ORIGINS", {})
    monkeypatch.setenv("GREENLIT_E2E", "1")
    monkeypatch.setenv("DEMO_CATALOG_PROBE_ORIGINS", "support-bot=http://127.0.0.1:9505")
    assert demo_catalog.probe_url(demo_catalog.CATALOG[0]) == (
        "http://host.docker.internal:9111/health"
    )


def test_the_setting_is_absent_from_the_api_surface() -> None:
    from app.main import app as api

    paths = " ".join(getattr(route, "path", "") for route in api.routes)
    assert "catalog-probe-origins" not in paths
    assert "demo-catalog" not in paths
    schema = api.openapi()
    serialized = str(schema)
    assert "DEMO_CATALOG_PROBE_ORIGINS" not in serialized
    assert "GREENLIT_E2E" not in serialized


def test_the_probe_keeps_only_the_health_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_entry(entry: demo_catalog.DemoApp) -> dict[str, str]:
        del entry
        return {"state": "down"}

    monkeypatch.setattr(demo_catalog, "probe_health", failing_entry)
    statuses: list[dict[str, Any]] = demo_catalog.statuses()
    assert [item["status"] for item in statuses] == [{"state": "down"}] * 8
