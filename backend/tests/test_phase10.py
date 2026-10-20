from __future__ import annotations

from collections.abc import AsyncIterator

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
    def unexpected_outbound(*args: object, **kwargs: object) -> None:
        pytest.fail("unavailable entry points must not execute")

    monkeypatch.setattr("app.services.connectors.make_http_client", unexpected_outbound)
    monkeypatch.setattr("app.services.connectors.subprocess.run", unexpected_outbound)

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
    assert website.status_code == 422, website.text
    assert "not available yet" in website.json()["detail"]

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
    assert mcp.status_code == 422, mcp.text
    assert "not available yet" in mcp.json()["detail"]

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
    assert str(phases["WEBSITE_URL"]).startswith("Phase 10")
    assert str(phases["MCP_SERVER"]).startswith("Phase 10")
    assert (
        next(item for item in types if item["type"] == "WEBSITE_URL")["implemented"]
        is False
    )
    assert (
        next(item for item in types if item["type"] == "MCP_SERVER")["implemented"]
        is False
    )
    assert any(item["type"] == "WEBSITE_URL" for item in types)
    assert any(item["type"] == "MCP_SERVER" for item in types)
    await client.aclose()
