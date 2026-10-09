from __future__ import annotations

import json as json_module
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db import Base, engine
from app.main import app


@pytest_asyncio.fixture(scope="module", autouse=True)
async def prepare_phase10_db() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield


async def signed_in_client() -> tuple[AsyncClient, str, str]:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"phase10-{__import__('uuid').uuid4()}@example.com",
            "password": "StrongPass1!",
            "workspace_name": "Phase 10 Workspace",
        },
    )
    assert signup.status_code == 200, signup.text
    return client, signup.json()["workspace"]["id"], signup.json()["access_token"]


@pytest.mark.asyncio
async def test_website_url_and_mcp_server_test_calls_are_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def get(
            self,
            url: str,
            headers: dict[str, str] | None = None,
        ) -> object:
            assert url == "https://example.com/"
            assert headers == {}
            return SimpleNamespace(
                status_code=200,
                text=(
                    "<html><head><title>Example Chat</title></head>"
                    "<body>hello</body></html>"
                ),
            )

        async def post(self, url: str, **kwargs: object) -> object:
            payload = kwargs["json"]
            payload_dict = payload if isinstance(payload, dict) else {}
            headers = kwargs.get("headers")
            assert url == "https://mcp.example.com/tool"
            assert payload_dict["tool"] == "chat"
            assert payload_dict["input"] == "hello"
            assert headers == {"Content-Type": "application/json"}
            return SimpleNamespace(
                status_code=200,
                content=json_module.dumps({"output": "MCP reply"}).encode(),
                json=lambda: {"output": "MCP reply"},
            )

    monkeypatch.setattr(
        "app.services.connectors.make_http_client",
        lambda timeout: FakeClient(),
    )

    def fake_run(
        argv: list[str],
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
    ) -> object:
        assert argv[:2] == ["python", "-m"]
        assert argv[2].endswith("chat_server.py")
        return SimpleNamespace(returncode=0, stdout="command ok\n", stderr="")

    monkeypatch.setattr("app.services.connectors.subprocess.run", fake_run)

    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}

    website = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "WEBSITE_URL",
            "settings": {
                "url": "https://example.com",
                "authorized": True,
                "request_cap": 10,
                "timeout_seconds": 10,
                "detect_widget": True,
            },
            "input": "hello",
        },
    )
    assert website.status_code == 200, website.text
    payload = website.json()
    assert payload["trace"]["output"].startswith("Discovered website")
    assert payload["detected_fields"]
    assert "steps.tool_calls" in payload["detected_fields"]

    mcp = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "MCP_SERVER",
            "settings": {
                "server_url": "https://mcp.example.com/tool",
                "tool_name": "chat",
                "prompt_template": "{{input}}",
                "timeout_seconds": 10,
            },
            "input": "hello",
        },
    )
    assert mcp.status_code == 200, mcp.text
    assert mcp.json()["trace"]["output"] == "MCP reply"

    await client.aclose()


@pytest.mark.asyncio
async def test_entry_point_registry_lists_phase10_types() -> None:
    client, workspace_id, access_token = await signed_in_client()
    response = await client.get(
        "/api/v1/entry-point-types",
        headers={"Authorization": "******"},
    )
    assert response.status_code == 200, response.text
    types = response.json()
    phases = {item["type"]: item["coming_in"] for item in types}
    assert phases["WEBSITE_URL"] == "phase 10"
    assert phases["MCP_SERVER"] == "phase 10"
    assert any(item["type"] == "WEBSITE_URL" for item in types)
    assert any(item["type"] == "MCP_SERVER" for item in types)
    await client.aclose()
