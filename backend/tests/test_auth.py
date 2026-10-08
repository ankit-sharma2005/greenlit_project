from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import Base, async_session_maker, engine
from app.main import app
from app.models import AuditLog, WorkspaceMembership


@pytest.mark.asyncio
async def test_health_and_readiness_endpoints() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        health = await client.get("/healthz")
        readiness = await client.get("/readyz")
        docs = await client.get("/docs")
        openapi = await client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ready"}
    assert docs.status_code == 200
    assert openapi.status_code == 200


@pytest_asyncio.fixture(scope="module", autouse=True)
async def prepare_db() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.mark.asyncio
async def test_signup_creates_workspace_and_access_token() -> None:
    email = f"signup-{uuid4()}@example.com"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": email,
                "password": "StrongPass1!",
                "workspace_name": "Ops Workspace",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email"] == email
    assert body["workspace"]["name"] == "Ops Workspace"
    assert "access_token" in body
    assert response.cookies.get("refresh_token")
    async with async_session_maker() as db:
        signup_audit = await db.scalar(
            select(AuditLog).where(
                AuditLog.user_id == UUID(body["user"]["id"]),
                AuditLog.action == "signup",
            )
        )
        workspace_audit = await db.scalar(
            select(AuditLog).where(
                AuditLog.user_id == UUID(body["user"]["id"]),
                AuditLog.action == "workspace_created",
            )
        )
    assert signup_audit is not None
    assert workspace_audit is not None


@pytest.mark.asyncio
async def test_login_refresh_and_logout_flow() -> None:
    email = f"login-{uuid4()}@example.com"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        signup = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": email,
                "password": "StrongPass1!",
                "workspace_name": "Design Studio",
            },
        )
        assert signup.status_code == 200, signup.text

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPass1!"},
        )
        assert login.status_code == 200, login.text
        access_token = login.json()["access_token"]
        async with async_session_maker() as db:
            login_audit = await db.scalar(
                select(AuditLog).where(
                    AuditLog.user_id == UUID(signup.json()["user"]["id"]),
                    AuditLog.action == "login",
                )
            )
        assert login_audit is not None
        original_refresh_token = client.cookies.get("refresh_token")
        assert original_refresh_token is not None
        refresh_as_access = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {original_refresh_token}"},
        )
        assert refresh_as_access.status_code == 401

        refreshed = await client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200, refreshed.text
        assert "access_token" in refreshed.json()
        rotated_refresh_token = client.cookies.get("refresh_token")
        assert rotated_refresh_token != original_refresh_token
        assert rotated_refresh_token is not None

        replay = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            cookies={"refresh_token": original_refresh_token},
        )
        replay_response = await replay.post("/api/v1/auth/refresh")
        assert replay_response.status_code == 401
        await replay.aclose()

        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me.status_code == 200, me.text
        assert me.json()["email"] == email

        logout = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert logout.status_code == 200, logout.text

        revoked = AsyncClient(
            transport=transport,
            base_url="http://testserver",
            cookies={"refresh_token": rotated_refresh_token},
        )
        revoked_response = await revoked.post("/api/v1/auth/refresh")
        assert revoked_response.status_code == 401
        await revoked.aclose()


@pytest.mark.asyncio
async def test_password_reset_uses_one_time_token_and_revokes_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"reset-{uuid4()}@example.com"
    delivered: dict[str, str] = {}

    def capture_reset_email(recipient: str, token: str) -> None:
        delivered.update(email=recipient, token=token)

    monkeypatch.setattr(
        "app.routers.auth.send_password_reset",
        capture_reset_email,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        signup = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": email,
                "password": "StrongPass1!",
                "workspace_name": "Reset Workspace",
            },
        )
        assert signup.status_code == 200, signup.text

        known_request = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": email}
        )
        unknown_request = await client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": f"missing-{uuid4()}@example.com"},
        )
        assert known_request.status_code == 200
        assert known_request.json() == unknown_request.json()
        assert delivered["email"] == email

        reset = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": delivered["token"], "password": "NewStrongPass2!"},
        )
        assert reset.status_code == 200, reset.text

        replay = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": delivered["token"], "password": "AnotherStrongPass3!"},
        )
        assert replay.status_code == 400

        revoked_refresh = await client.post("/api/v1/auth/refresh")
        assert revoked_refresh.status_code == 401

        old_password_login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPass1!"},
        )
        new_password_login = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "NewStrongPass2!"},
        )
        assert old_password_login.status_code == 401
        assert new_password_login.status_code == 200


@pytest.mark.asyncio
async def test_viewer_and_cross_workspace_access_are_forbidden() -> None:
    primary_email = f"owner-{uuid4()}@example.com"
    secondary_email = f"viewer-{uuid4()}@example.com"
    secondary_email_2 = f"cross-{uuid4()}@example.com"

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        primary_signup = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": primary_email,
                "password": "StrongPass1!",
                "workspace_name": "Primary Workspace",
            },
        )
        assert primary_signup.status_code == 200, primary_signup.text
        primary_workspace_id = primary_signup.json()["workspace"]["id"]
        primary_token = primary_signup.json()["access_token"]

        viewer_signup = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": secondary_email,
                "password": "StrongPass1!",
                "workspace_name": "Viewer Workspace",
            },
        )
        viewer_token = viewer_signup.json()["access_token"]
        viewer_workspace_id = viewer_signup.json()["workspace"]["id"]

        async with async_session_maker() as db:
            membership = await db.scalar(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == UUID(viewer_workspace_id)
                )
            )
            assert membership is not None
            membership.role = "viewer"
            await db.commit()

        viewer_login = await client.post(
            "/api/v1/auth/login",
            json={"email": secondary_email, "password": "StrongPass1!"},
        )
        viewer_token = viewer_login.json()["access_token"]

        blocked = await client.get(
            f"/api/v1/workspaces/{viewer_workspace_id}/engineer/insights",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert blocked.status_code == 403

        blocked_admin = await client.get(
            f"/api/v1/workspaces/{viewer_workspace_id}/audit",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert blocked_admin.status_code == 403

        cross_signup = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": secondary_email_2,
                "password": "StrongPass1!",
                "workspace_name": "Second Workspace",
            },
        )
        other_workspace_id = cross_signup.json()["workspace"]["id"]

        cross_access = await client.get(
            f"/api/v1/workspaces/{other_workspace_id}/viewer/summary",
            headers={"Authorization": f"Bearer {primary_token}"},
        )
        assert cross_access.status_code == 403

        own_summary = await client.get(
            f"/api/v1/workspaces/{primary_workspace_id}/viewer/summary",
            headers={"Authorization": f"Bearer {primary_token}"},
        )
        assert own_summary.status_code == 200
