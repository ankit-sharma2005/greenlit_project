from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_phase9_api_tokens_enable_ci_regression_checks() -> None:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"phase9-{uuid4()}@example.com",
            "password": "StrongPass1!",
            "workspace_name": "Phase 9 Workspace",
        },
    )
    assert signup.status_code == 200, signup.text
    workspace_id = signup.json()["workspace"]["id"]
    access_token = signup.json()["access_token"]

    create_token = await client.post(
        f"/api/v1/workspaces/{workspace_id}/api-tokens",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "ci-token", "scopes": ["ci:read", "ci:write"]},
    )
    assert create_token.status_code == 200, create_token.text
    created = create_token.json()
    assert created["name"] == "ci-token"
    assert created["token"].startswith("gl_")
    assert "ci:read" in created["scopes"]

    regression = await client.post(
        f"/api/v1/workspaces/{workspace_id}/ci/regression-check",
        headers={"Authorization": f"Bearer {created['token']}"},
        json={
            "status": "WARN",
            "checks": [
                {"name": "backend-tests", "status": "PASS"},
                {"name": "lint", "status": "WARN"},
                {"name": "typecheck", "status": "PASS"},
            ],
            "message": "One check produced warnings",
        },
    )
    assert regression.status_code == 200, regression.text
    payload = regression.json()
    assert payload["status"] == "WARN"
    assert payload["api_token"] == "ci-token"

    header_regression = await client.post(
        f"/api/v1/workspaces/{workspace_id}/ci/regression-check",
        headers={"x-api-token": created["token"]},
        json={
            "checks": [{"name": "backend-tests", "status": "BLOCK"}],
            "message": "Failure detected",
        },
    )
    assert header_regression.status_code == 200, header_regression.text
    assert header_regression.json()["status"] == "BLOCK"

    list_tokens = await client.get(
        f"/api/v1/workspaces/{workspace_id}/api-tokens",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert list_tokens.status_code == 200, list_tokens.text
    assert any(item["name"] == "ci-token" for item in list_tokens.json())

    await client.aclose()
