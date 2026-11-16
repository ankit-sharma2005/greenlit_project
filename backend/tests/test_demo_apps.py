"""The demo-app catalog: status, connect and the safety limits around them."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services import demo_catalog

PASSWORD = "correct horse battery staple"


def register(client: TestClient, email: str = "ada@example.com") -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Ada", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def test_the_catalog_holds_the_eight_fixed_apps() -> None:
    ids = [entry.id for entry in demo_catalog.CATALOG]
    assert ids == [
        "support-bot",
        "docs-rag",
        "stream-bot",
        "tool-agent",
        "math-solver",
        "reliability-lab",
        "vault-bot",
        "site-bot",
    ]
    ports = [entry.url.split(":")[2].split("/")[0] for entry in demo_catalog.CATALOG]
    assert ports == [
        "9111",
        "9112",
        "9113",
        "9114",
        "9115",
        "9116",
        "9117",
        "9118",
    ]
    for entry in demo_catalog.CATALOG:
        assert entry.name and entry.description
        assert entry.start_bash and entry.start_windows
        assert entry.modes
        assert entry.url.startswith("http://host.docker.internal:")
    assert demo_catalog.get_entry("tool-agent").mcp_tool == "ask_assistant"
    assert demo_catalog.get_entry("math-solver").timeout_seconds == 30
    for entry in demo_catalog.CATALOG[:3]:
        assert entry.timeout_seconds == 150
    assert "never be exposed to the internet" in demo_catalog.WARNING


def test_the_probe_keeps_only_the_four_health_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200

        def read(self, _limit: int) -> bytes:
            return json.dumps(
                {
                    "status": "ok",
                    "app": "support-bot",
                    "mode": "guarded",
                    "provider": "ollama",
                    "model": "hermes3:8b",
                    "secret": "must not travel",
                }
            ).encode()

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(
        demo_catalog.urllib.request,
        "build_opener",
        lambda *_handlers: type("O", (), {"open": lambda self, url, timeout: FakeResponse()})(),
    )
    status = demo_catalog.probe_health(demo_catalog.CATALOG[0])
    assert status == {
        "state": "up",
        "app": "support-bot",
        "mode": "guarded",
        "provider": "ollama",
        "model": "hermes3:8b",
    }


def test_the_status_endpoint_shows_up_and_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)

    def fake_probe(entry: demo_catalog.DemoApp) -> dict[str, str]:
        if entry.id == "math-solver":
            return {"state": "down"}
        return {
            "state": "up",
            "app": entry.id,
            "mode": "correct",
            "provider": "none",
            "model": "none",
        }

    monkeypatch.setattr(demo_catalog, "probe_health", fake_probe)
    body = client.get("/api/v1/demo-apps").json()
    assert len(body["items"]) == 8
    assert body["items"][0]["status"]["state"] == "up"
    assert body["items"][0]["status"]["mode"] == "correct"
    assert body["items"][4]["status"] == {"state": "down"}
    assert body["warning"] == demo_catalog.WARNING


def test_a_request_cannot_choose_the_address(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    probed: list[str] = []

    def recording_probe(entry: demo_catalog.DemoApp) -> dict[str, str]:
        probed.append(entry.id)
        return {"state": "down"}

    monkeypatch.setattr(demo_catalog, "probe_health", recording_probe)
    response = client.get(
        "/api/v1/demo-apps",
        params={"url": "http://169.254.169.254/latest", "id": "evil", "host": "10.0.0.1"},
    )
    assert response.status_code == 200
    # Exactly the catalog, in catalog order: the query string changed nothing.
    assert probed == [entry.id for entry in demo_catalog.CATALOG]
    assert {item["url"] for item in response.json()["items"]} == {
        entry.url for entry in demo_catalog.CATALOG
    }


def test_connect_saves_one_target_and_a_second_call_reuses_it(client: TestClient) -> None:
    register(client)
    first = client.post("/api/v1/demo-apps/support-bot/connect")
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["created"] is True
    target = body["target"]
    assert target["name"] == "Acme support bot"
    assert target["url"] == "http://host.docker.internal:9111/"
    assert target["answer_path"] == "$.answer"
    assert target["timeout_seconds"] == 150
    # The allowance is on this catalog target only, and the warning says so.
    assert target["allow_private_targets"] is True
    assert "never be exposed to the internet" in body["warning"]

    second = client.post("/api/v1/demo-apps/support-bot/connect")
    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["target"]["id"] == target["id"]
    assert client.get("/api/v1/saved-targets").json()["total"] == 1


def test_an_unknown_app_is_a_404(client: TestClient) -> None:
    register(client)
    assert client.post("/api/v1/demo-apps/does-not-exist/connect").status_code == 404


def test_connect_refuses_to_take_an_address(client: TestClient) -> None:
    register(client)
    response = client.post(
        "/api/v1/demo-apps/support-bot/connect",
        json={"url": "http://169.254.169.254/"},
    )
    assert response.status_code == 422
    assert client.get("/api/v1/saved-targets").json()["total"] == 0


def test_two_accounts_keep_their_own_targets(client: TestClient) -> None:
    register(client, "ada@example.com")
    mine = client.post("/api/v1/demo-apps/docs-rag/connect").json()["target"]
    client.post("/api/v1/auth/logout")

    register(client, "grace@example.com")
    theirs = client.post("/api/v1/demo-apps/docs-rag/connect").json()["target"]
    assert theirs["id"] != mine["id"]
    listed = client.get("/api/v1/saved-targets").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == theirs["id"]


def test_the_responses_carry_no_key(client: TestClient) -> None:
    register(client)
    payload = (
        client.get("/api/v1/demo-apps").text
        + client.post("/api/v1/demo-apps/stream-bot/connect").text
    )
    lowered = payload.lower()
    for forbidden in ("api_key", "authorization", "bearer", "password"):
        assert forbidden not in lowered


def test_the_endpoints_need_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/demo-apps").status_code == 401
    assert client.post("/api/v1/demo-apps/support-bot/connect").status_code == 401


def test_app_dict_carries_the_connector_fields() -> None:
    entry: Any = demo_catalog.CATALOG[0]
    body = demo_catalog.app_dict(entry)
    assert body["body_template"] == '{"question": "{{question}}"}'
    assert body["response_format"] == "json"
    assert body["modes"][0]["mode"] == "guarded"
