from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db import Base, async_session_maker, engine
from app.main import app
from app.models import (
    AppVersion,
    ChatConversation,
    ChatMessage,
    ConnectorProfile,
    ConnectorTest,
    Dataset,
    DatasetItem,
    DatasetVersion,
    ProviderConfig,
    WorkspaceMembership,
)
from app.phase2_schemas import (
    CONNECTOR_SETTINGS_MODELS,
    ConnectorSaveRequest,
    ConnectorTestCallRequest,
)
from app.routers import phase2 as phase2_router
from app.routers.chat import redact_chat_text
from app.routers.phase2 import gateway
from app.services import connectors
from app.services.connectors import validate_connector_settings
from app.services.llm_gateway import (
    ChatResult,
    LLMGateway,
    normalize_provider_base_url,
)
from app.services.rate_limit import DailyQuotaPaused, ProviderRateLimiter
from app.services.secrets import decrypt_secret, encrypt_secret


@pytest_asyncio.fixture(scope="module", autouse=True)
async def prepare_phase2_db() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(autouse=True)
def reset_provider_rate_limiter() -> None:
    gateway.rate_limiter.reset()


async def signed_in_client() -> tuple[AsyncClient, str, str]:
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": f"phase2-{uuid4()}@example.com",
            "password": "StrongPass1!",
            "workspace_name": "Phase 2 Workspace",
        },
    )
    assert signup.status_code == 200, signup.text
    return (
        client,
        signup.json()["workspace"]["id"],
        signup.json()["access_token"],
    )


async def create_tested_provider(
    client: AsyncClient,
    workspace_id: str,
    access_token: str,
    payload: Mapping[str, object],
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    tested = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers/test-connection",
        headers=headers,
        json=payload,
    )
    assert tested.status_code == 200, tested.text
    return await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers",
        headers=headers,
        json={**payload, "test_token": tested.json()["test_token"]},
    )


@pytest.mark.asyncio
async def test_provider_test_is_stateless_and_save_rejects_casefolded_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle_provider_request(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={"data": [{"id": "test-model", "object": "model"}]},
            )
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        gateway,
        "client_factory",
        mock_provider_client(handle_provider_request),
    )
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {
        "name": "Unique provider",
        "provider_type": "custom",
        "base_url": "https://mock-provider.example/v1",
    }
    tested = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers/test-connection",
        headers=headers,
        json=payload,
    )
    assert tested.status_code == 200, tested.text
    async with async_session_maker() as db:
        count_before_save = await db.scalar(
            select(func.count())
            .select_from(ProviderConfig)
            .where(ProviderConfig.workspace_id == UUID(workspace_id))
        )
    assert count_before_save == 0

    created = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers",
        headers=headers,
        json={**payload, "test_token": tested.json()["test_token"]},
    )
    assert created.status_code == 201, created.text

    changed_case = {**payload, "name": "UNIQUE PROVIDER"}
    duplicate_test = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers/test-connection",
        headers=headers,
        json=changed_case,
    )
    assert duplicate_test.status_code == 200, duplicate_test.text
    duplicate = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers",
        headers=headers,
        json={**changed_case, "test_token": duplicate_test.json()["test_token"]},
    )
    assert duplicate.status_code == 409
    assert "provider with this name already exists" in duplicate.json()["detail"]
    await client.aclose()


@pytest.mark.asyncio
async def test_project_names_are_case_insensitive_and_duplicates_return_conflict() -> (
    None
):
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    path = f"/api/v1/workspaces/{workspace_id}/projects"
    created = await client.post(
        path,
        headers=headers,
        json={"name": "Demo RAG Bot", "description": "Original"},
    )
    assert created.status_code == 201, created.text
    duplicate = await client.post(
        path,
        headers=headers,
        json={"name": "demo rag bot", "description": "Different"},
    )
    assert duplicate.status_code == 409
    assert "project with this name already exists" in duplicate.json()["detail"]
    await client.aclose()


def test_ollama_base_url_normalization_handles_both_supported_forms() -> None:
    assert (
        normalize_provider_base_url("ollama", "http://host.docker.internal:11434")
        == "http://host.docker.internal:11434/v1"
    )
    assert (
        normalize_provider_base_url("ollama", "http://host.docker.internal:11434/v1")
        == "http://host.docker.internal:11434/v1"
    )
    assert (
        normalize_provider_base_url("ollama", "http://host.docker.internal:11434/v1/v1")
        == "http://host.docker.internal:11434/v1"
    )


def mock_provider_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[..., httpx.AsyncClient]:
    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            **kwargs,
        )

    return factory


@pytest.mark.asyncio
async def test_provider_connection_works_for_github_and_ollama_without_exposing_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.llm_gateway.settings.allowed_private_hosts",
        "host.docker.internal",
    )
    observed_authorization: list[str] = []
    observed_requests: list[httpx.Request] = []

    def handle_provider_request(request: httpx.Request) -> httpx.Response:
        observed_authorization.append(request.headers.get("authorization", ""))
        observed_requests.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [{"id": "greenlit-test-model", "object": "model"}],
                },
            )
        assert str(request.url) == (
            "http://host.docker.internal:11434/v1/chat/completions"
        )
        assert request.read()
        return httpx.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "created": 0,
                "model": "hermes3:8b",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OK"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
                },
            },
        )

    monkeypatch.setattr(
        gateway,
        "client_factory",
        mock_provider_client(handle_provider_request),
    )
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    github_secret = f"github-secret-{uuid4()}"

    github_payload = {
        "name": "GitHub Models",
        "provider_type": "github_models",
        "api_key": github_secret,
    }
    github = await create_tested_provider(
        client, workspace_id, access_token, github_payload
    )
    assert github.status_code == 201, github.text
    github_provider_id = github.json()["id"]

    github_test = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers/test-connection",
        headers=headers,
        json=github_payload,
    )
    assert github_test.status_code == 200, github_test.text
    assert github_test.json()["models"] == ["greenlit-test-model"]
    assert github_secret not in github.text
    assert github_secret not in github_test.text
    assert observed_authorization[0] == f"Bearer {github_secret}"

    github_test = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers/"
        f"{github_provider_id}/test-connection",
        headers=headers,
    )
    assert github_test.status_code == 200, github_test.text
    assert github_test.json()["models"] == ["greenlit-test-model"]
    assert github_secret not in github.text
    assert github_secret not in github_test.text
    assert observed_authorization[0] == f"Bearer {github_secret}"

    ollama = await create_tested_provider(
        client,
        workspace_id,
        access_token,
        {
            "name": "Local Ollama",
            "provider_type": "ollama",
            "base_url": "http://host.docker.internal:11434/v1/v1",
        },
    )
    assert ollama.status_code == 201, ollama.text
    assert ollama.json()["test_model"] == "hermes3:8b"
    assert ollama.json()["base_url"] == "http://host.docker.internal:11434/v1"
    ollama_test = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers/"
        f"{ollama.json()['id']}/test-connection",
        headers=headers,
    )
    assert ollama_test.status_code == 200, ollama_test.text
    assert ollama_test.json()["test_model"] == "hermes3:8b"
    assert ollama_test.json()["output"] == "OK"
    assert json.loads(observed_requests[-1].content)["model"] == "hermes3:8b"
    assert len(observed_authorization) == 5

    async with async_session_maker() as db:
        provider = await db.scalar(
            select(ProviderConfig).where(ProviderConfig.id == UUID(github_provider_id))
        )
    assert provider is not None
    assert provider.api_key_encrypted != github_secret
    assert decrypt_secret(provider.api_key_encrypted or "") == github_secret
    assert github_secret not in json.dumps(github_test.json())
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_connection_exposes_and_logs_upstream_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "app.services.llm_gateway.settings.allowed_private_hosts",
        "localhost,host.docker.internal",
    )

    def handle_provider_request(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.read())["model"] == "missing-model:tag"
        return httpx.Response(
            404,
            json={"error": "model missing-model:tag was not found"},
        )

    monkeypatch.setattr(
        gateway,
        "client_factory",
        mock_provider_client(handle_provider_request),
    )
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers/test-connection",
        headers=headers,
        json={
            "name": "Local Ollama",
            "provider_type": "ollama",
            "test_model": "missing-model:tag",
        },
    )
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["upstream_status_code"] == 404
    assert "model missing-model:tag was not found" in detail["upstream_body"]
    assert any(
        getattr(record, "upstream_status_code", None) == 404
        and "model missing-model:tag was not found"
        in getattr(record, "upstream_body", "")
        for record in caplog.records
    )
    assert "HTTP 404" in caplog.text
    assert "model missing-model:tag was not found" in caplog.text
    await client.aclose()


@pytest.mark.asyncio
async def test_registry_lists_all_thirteen_types_and_validates_type_settings() -> None:
    client, workspace_id, access_token = await signed_in_client()
    response = await client.get("/api/v1/entry-point-types")
    assert response.status_code == 200
    types = response.json()
    assert len(types) == 13
    assert [item["type"] for item in types] == [
        "HTTP_ENDPOINT",
        "PYTHON_FUNCTION",
        "PYTHON_SDK_TRACED",
        "PROMPT_APP",
        "BUILTIN_RAG_APP",
        "BUILTIN_AGENT_APP",
        "DOCKER_IMAGE",
        "GIT_REPO",
        "CLI_COMMAND",
        "PROXY_MODE",
        "UPLOAD_OUTPUTS",
        "WEBSITE_URL",
        "MCP_SERVER",
    ]
    assert all(item["settings_schema"] for item in types[:6])
    assert types[1]["implemented"] is False
    assert "isolated execution" in str(types[1]["coming_in"]).lower()
    assert types[2]["implemented"] is False
    assert "isolated execution" in str(types[2]["coming_in"]).lower()
    assert types[6]["implemented"] is False
    assert "real sandbox" in str(types[6]["coming_in"]).lower()
    assert types[9]["implemented"] is False
    assert "real sandbox" in str(types[9]["coming_in"]).lower()
    assert "manual browser verification" in str(types[11]["coming_in"]).lower()
    assert "manual mcp verification" in str(types[12]["coming_in"]).lower()

    invalid = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "entry_point_type": "BUILTIN_RAG_APP",
            "settings": {"chunk_size": 100, "chunk_overlap": 100},
            "input": "sample",
        },
    )
    assert invalid.status_code == 422

    unavailable_python = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "entry_point_type": "PYTHON_FUNCTION",
            "settings": {
                "module": "sample_app",
                "function": "run",
            },
            "input": "sample",
        },
    )
    assert unavailable_python.status_code == 422
    assert "isolated execution runner" in unavailable_python.json()["detail"]

    unavailable_connector_types = [
        "DOCKER_IMAGE",
        "GIT_REPO",
        "CLI_COMMAND",
        "PROXY_MODE",
        "WEBSITE_URL",
        "MCP_SERVER",
    ]
    for entry_point_type in unavailable_connector_types:
        response = await client.post(
            f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "entry_point_type": entry_point_type,
                "settings": {
                    "url": "https://example.com",
                    "authorized": True,
                    "request_cap": 10,
                    "timeout_seconds": 10,
                    "detect_widget": True,
                }
                if entry_point_type == "WEBSITE_URL"
                else {
                    "image": "busybox:latest",
                    "command": "echo test",
                    "memory_mb": 256,
                    "cpus": 0.5,
                    "timeout_seconds": 12,
                }
                if entry_point_type == "DOCKER_IMAGE"
                else {
                    "repo_url": "https://example.com/repo.git",
                    "branch": "main",
                    "command": 'python -c "print(1)"',
                    "timeout_seconds": 12,
                }
                if entry_point_type == "GIT_REPO"
                else {
                    "command": "echo test",
                    "working_directory": ".",
                    "timeout_seconds": 12,
                }
                if entry_point_type == "CLI_COMMAND"
                else {
                    "base_url": "https://proxy.example.com/chat",
                    "model": "proxy-llm",
                    "request_body_template": (
                        '{"model": "{{model}}", "input": "{{input}}"}'
                    ),
                    "allow_private_targets": False,
                    "timeout_seconds": 12,
                }
                if entry_point_type == "PROXY_MODE"
                else {
                    "server_url": "https://mcp.example.com/tool",
                    "tool_name": "chat",
                    "prompt_template": "{{input}}",
                    "timeout_seconds": 12,
                },
                "input": "sample",
            },
        )
        assert response.status_code == 422, (entry_point_type, response.text)
        assert "not available yet" in response.json()["detail"].lower()
    await client.aclose()


def test_connector_entry_point_payloads_validate_against_backend_models() -> None:
    provider_id = str(uuid4())
    examples = [
        {
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": {
                "rows": [{"input": "sample", "output": "answer"}],
                "input_field": "input",
                "output_field": "output",
            },
            "input": "sample",
        },
        {
            "entry_point_type": "HTTP_ENDPOINT",
            "settings": {
                "url": "https://app.example.com/run",
                "method": "POST",
                "request_body_template": '{"input": {{input}}}',
                "output_field": "data.answer",
                "timeout_seconds": 15,
            },
            "credentials": {"api_key": "test-only"},
            "input": "sample",
        },
        {
            "entry_point_type": "PROMPT_APP",
            "settings": {"system_prompt": "Answer clearly.", "temperature": 0},
            "provider_id": provider_id,
            "model": "test-model",
            "input": "sample",
        },
    ]

    for example in examples:
        test_request = ConnectorTestCallRequest.model_validate(example)
        validate_connector_settings(
            test_request.entry_point_type, test_request.settings
        )
        save_example = {
            key: value for key, value in example.items() if key != "input"
        }
        save_example.update(
            {"name": "Test connector", "test_call_id": "test-token"}
        )
        save_request = ConnectorSaveRequest.model_validate(save_example)
        validate_connector_settings(
            save_request.entry_point_type, save_request.settings
        )
        assert "provider_id" not in save_request.settings
        assert "model" not in save_request.settings


@pytest.mark.asyncio
async def test_unknown_connector_setting_returns_clear_422() -> None:
    client, workspace_id, access_token = await signed_in_client()
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": {
                "rows": [{"input": "sample", "output": "answer"}],
                "unknown_setting": "unexpected",
            },
            "input": "sample",
        },
    )

    assert response.status_code == 422
    assert "Unsupported setting 'unknown_setting'" in response.json()["detail"]
    await client.aclose()


@pytest.mark.asyncio
async def test_duplicate_connector_name_returns_helpful_conflict() -> None:
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    project_response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json={"name": "Connector name conflict"},
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    settings = {
        "rows": [{"input": "sample", "output": "first answer"}],
        "input_field": "input",
        "output_field": "output",
    }
    first_test = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": settings,
            "input": "sample",
        },
    )
    assert first_test.status_code == 200, first_test.text
    first_save = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}/connectors",
        headers=headers,
        json={
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": settings,
            "test_call_id": first_test.json()["test_call_id"],
            "name": "Existing outputs",
        },
    )
    assert first_save.status_code == 201, first_save.text

    changed_settings = {
        **settings,
        "rows": [{"input": "sample", "output": "different answer"}],
    }
    second_test = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": changed_settings,
            "input": "sample",
        },
    )
    assert second_test.status_code == 200, second_test.text
    duplicate_save = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}/connectors",
        headers=headers,
        json={
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": changed_settings,
            "test_call_id": second_test.json()["test_call_id"],
            "name": "Existing outputs",
        },
    )

    assert duplicate_save.status_code == 409
    assert (
        duplicate_save.json()["detail"]
        == "A connector with this name already exists in this project."
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_unavailable_execution_connectors_are_rejected_without_running_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> object:
            assert url == "https://proxy.example.com/chat"
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"output": "proxy ok"},
                text="proxy ok",
            )

    monkeypatch.setattr(
        "app.services.connectors.make_http_client",
        lambda timeout: FakeClient(),
    )

    def fake_run(
        argv: list[str],
        capture_output: bool,
        text: bool,
        timeout: int | None,
        check: bool,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        input: str | None = None,
    ) -> object:
        if argv[0] == "docker":
            assert "--network" in argv
            assert argv[argv.index("--network") + 1] == "none"
            return SimpleNamespace(returncode=0, stdout="docker ok\n", stderr="")
        if argv[0] == "git":
            assert argv[1] == "clone"
            return SimpleNamespace(returncode=0, stdout="git ok\n", stderr="")
        if argv[0] == "python":
            assert cwd is not None
            return SimpleNamespace(returncode=0, stdout="cli ok\n", stderr="")
        if argv[0] == "echo":
            return SimpleNamespace(returncode=0, stdout="echo ok\n", stderr="")
        raise AssertionError(f"Unexpected command: {argv!r}")

    monkeypatch.setattr("app.services.connectors.subprocess.run", fake_run)

    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}

    docker = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "DOCKER_IMAGE",
            "settings": {
                "image": "busybox:latest",
                "command": "echo docker-ok",
                "memory_mb": 256,
                "cpus": 0.5,
                "timeout_seconds": 12,
            },
            "input": "sample",
        },
    )
    assert docker.status_code == 422, docker.text
    assert "verified real Docker sandbox runner" in docker.json()["detail"]

    git_repo = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "GIT_REPO",
            "settings": {
                "repo_url": "https://example.com/repo.git",
                "branch": "main",
                "command": "python -c \"print('git-ok')\"",
                "timeout_seconds": 12,
            },
            "input": "sample",
        },
    )
    assert git_repo.status_code == 422, git_repo.text
    assert "not available yet" in git_repo.json()["detail"]

    cli = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "CLI_COMMAND",
            "settings": {
                "command": "echo cli-ok",
                "working_directory": ".",
                "timeout_seconds": 12,
            },
            "input": "sample",
        },
    )
    assert cli.status_code == 422, cli.text
    assert "not available yet" in cli.json()["detail"]

    proxy = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "PROXY_MODE",
            "settings": {
                "base_url": "https://proxy.example.com/chat",
                "model": "proxy-llm",
                "request_body_template": '{"model": "{{model}}", "input": "{{input}}"}',
                "allow_private_targets": False,
                "timeout_seconds": 12,
            },
            "input": "sample",
        },
    )
    assert proxy.status_code == 422, proxy.text
    assert "not available yet" in proxy.json()["detail"]

    await client.aclose()


@pytest.mark.asyncio
async def test_prompt_and_rag_test_calls_gate_saves_and_create_app_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_bodies: list[dict[str, object]] = []

    def handle_completion(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [{"id": "greenlit-model", "object": "model"}],
                },
            )
        request_bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-phase2",
                "object": "chat.completion",
                "created": 1,
                "model": "greenlit-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "A useful answer."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 4,
                    "total_tokens": 16,
                },
            },
        )

    monkeypatch.setattr(
        gateway,
        "client_factory",
        mock_provider_client(handle_completion),
    )
    client, workspace_id, access_token = await signed_in_client()
    provider = await create_tested_provider(
        client,
        workspace_id,
        access_token,
        {
            "name": "Mock chat provider",
            "provider_type": "custom",
            "base_url": "https://mock-provider.example/v1",
            "api_key": "phase2-provider-secret",
        },
    )
    assert provider.status_code == 201, provider.text

    headers = {"Authorization": f"Bearer {access_token}"}
    project = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json={"name": "Prompt project", "description": "Phase 2 integration test"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    prompt_settings = {
        "system_prompt": "Answer accurately.",
        "temperature": 0,
    }
    provider_values = {
        "provider_id": provider.json()["id"],
        "model": "greenlit-model",
    }
    prompt_call = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "PROMPT_APP",
            "settings": prompt_settings,
            **provider_values,
            "input": "What is GreenLit?",
        },
    )
    assert prompt_call.status_code == 200, prompt_call.text
    prompt_result = prompt_call.json()
    assert prompt_result["trace"]["output"] == "A useful answer."
    assert prompt_result["trace"]["usage"] == {"tokens_in": 12, "tokens_out": 4}
    assert "model_used" in prompt_result["detected_fields"]
    assert "steps.retrieved_chunks" in prompt_result["missing_fields"]
    assert "phase2-provider-secret" not in prompt_call.text

    tampered = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}/connectors",
        headers=headers,
        json={
            "entry_point_type": "PROMPT_APP",
            "settings": prompt_settings,
            **{**provider_values, "model": "different-model"},
            "test_call_id": prompt_result["test_call_id"],
        },
    )
    assert tampered.status_code == 409

    saved_prompt = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}/connectors",
        headers=headers,
        json={
            "entry_point_type": "PROMPT_APP",
            "settings": prompt_settings,
            **provider_values,
            "test_call_id": prompt_result["test_call_id"],
        },
    )
    assert saved_prompt.status_code == 201, saved_prompt.text
    assert saved_prompt.json()["app_version"] == 2

    rag_settings = {
        "documents": [
            {
                "title": "GreenLit guide",
                "text": "GreenLit evaluates language model applications before launch. "
                "It uses a fixed dataset and evidence-based criteria.",
            }
        ],
        "chunk_size": 120,
        "chunk_overlap": 20,
        "top_k": 1,
        "prompt": "Answer from the supplied context only.",
    }
    rag_call = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "BUILTIN_RAG_APP",
            "settings": rag_settings,
            **provider_values,
            "input": "What does GreenLit evaluate?",
        },
    )
    assert rag_call.status_code == 200, rag_call.text
    rag_result = rag_call.json()
    assert rag_result["trace"]["steps"]["retrieved_chunks"]
    rag_messages = request_bodies[-1]["messages"]
    assert isinstance(rag_messages, list)
    rag_system_message = rag_messages[0]
    assert isinstance(rag_system_message, dict)
    rag_system_content = rag_system_message["content"]
    assert isinstance(rag_system_content, str)
    assert "GreenLit guide" in rag_system_content

    saved_rag = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}/connectors",
        headers=headers,
        json={
            "entry_point_type": "BUILTIN_RAG_APP",
            "settings": rag_settings,
            **provider_values,
            "test_call_id": rag_result["test_call_id"],
        },
    )
    assert saved_rag.status_code == 201, saved_rag.text
    assert saved_rag.json()["app_version"] == 3

    versions = await client.get(
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}/app-versions",
        headers=headers,
    )
    assert [version["version"] for version in versions.json()] == [1, 2, 3]
    connectors_response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}/connectors",
        headers=headers,
    )
    assert [item["entry_point_type"] for item in connectors_response.json()] == [
        "PROMPT_APP",
        "BUILTIN_RAG_APP",
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_http_test_call_redacts_and_encrypts_secret_headers(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    seen_secret: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        authorization = request.headers["authorization"]
        seen_secret.append(authorization)
        return httpx.Response(
            200,
            json={"answer": f"echoed {authorization}"},
        )

    def client_factory(timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handle_request),
            timeout=timeout,
            follow_redirects=False,
        )

    monkeypatch.setattr(connectors, "make_http_client", client_factory)
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    project = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json={"name": "HTTP connector"},
    )
    project_id = project.json()["id"]
    secret = f"header-secret-{uuid4()}"
    settings = {
        "url": "http://127.0.0.1:9999/test",
        "method": "POST",
        "request_body_template": '{"input": {{input}}}',
        "input_field": "input",
        "output_field": "answer",
        "timeout_seconds": 10,
        "allow_private_targets": True,
    }
    test_call = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "HTTP_ENDPOINT",
            "settings": settings,
            "credentials": {"Authorization": f"Bearer {secret}"},
            "input": "sample",
        },
    )
    assert test_call.status_code == 200, test_call.text
    assert seen_secret == [f"Bearer {secret}"]
    assert secret not in test_call.text
    assert secret not in caplog.text
    assert "[REDACTED]" in test_call.json()["trace"]["output"]

    saved = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}/connectors",
        headers=headers,
        json={
            "entry_point_type": "HTTP_ENDPOINT",
            "settings": settings,
            "credentials": {"Authorization": f"Bearer {secret}"},
            "test_call_id": test_call.json()["test_call_id"],
        },
    )
    assert saved.status_code == 201, saved.text
    async with async_session_maker() as db:
        connector = await db.scalar(
            select(ConnectorProfile).where(
                ConnectorProfile.id == UUID(saved.json()["id"])
            )
        )
    assert connector is not None
    assert connector.encrypted_credentials is not None
    assert secret not in connector.encrypted_credentials
    assert json.loads(decrypt_secret(connector.encrypted_credentials)) == {
        "Authorization": f"Bearer {secret}"
    }
    assert secret not in saved.text
    assert secret not in caplog.text
    await client.aclose()


@pytest.mark.asyncio
async def test_builtin_agent_executes_schema_validated_mock_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_requests: list[dict[str, object]] = []

    def handle_completion(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [{"id": "agent-model", "object": "model"}],
                },
            )
        body = json.loads(request.content)
        chat_requests.append(body)
        if len(chat_requests) == 1:
            output = json.dumps(
                {"tool": "lookup_weather", "arguments": {"city": "Wellington"}}
            )
        else:
            output = "The weather in Wellington is mild."
        return httpx.Response(
            200,
            json={
                "id": f"chatcmpl-agent-{len(chat_requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "agent-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": output},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 7,
                    "total_tokens": 22,
                },
            },
        )

    monkeypatch.setattr(
        gateway,
        "client_factory",
        mock_provider_client(handle_completion),
    )
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    provider = await create_tested_provider(
        client,
        workspace_id,
        access_token,
        {
            "name": "Mock agent provider",
            "provider_type": "custom",
            "base_url": "https://mock-agent.example/v1",
        },
    )
    assert provider.status_code == 201, provider.text
    settings = {
        "max_steps": 3,
        "tools": [
            {
                "name": "lookup_weather",
                "description": "Look up a city's weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                    "additionalProperties": False,
                },
                "mock_result": {"forecast": "mild"},
            }
        ],
    }
    result = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "BUILTIN_AGENT_APP",
            "settings": settings,
            "provider_id": provider.json()["id"],
            "model": "agent-model",
            "input": "What is the weather in Wellington?",
        },
    )

    assert result.status_code == 200, result.text
    trace = result.json()["trace"]
    assert trace["output"] == "The weather in Wellington is mild."
    assert trace["steps"]["tool_calls"] == [
        {
            "name": "lookup_weather",
            "args": {"city": "Wellington"},
            "result": {"forecast": "mild"},
            "error": None,
        }
    ]
    assert "steps.tool_calls" in result.json()["detected_fields"]
    assert len(chat_requests) == 2
    second_messages = chat_requests[1]["messages"]
    assert isinstance(second_messages, list)
    assert "Mock tool result" in str(second_messages[-1])
    await client.aclose()


@pytest.mark.asyncio
async def test_builtin_agent_rejects_tool_arguments_outside_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle_completion(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [{"id": "agent-model", "object": "model"}],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-invalid-tool",
                "object": "chat.completion",
                "created": 1,
                "model": "agent-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "tool": "lookup_weather",
                                    "arguments": {"city": "Wellington", "extra": True},
                                }
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    monkeypatch.setattr(
        gateway,
        "client_factory",
        mock_provider_client(handle_completion),
    )
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    provider = await create_tested_provider(
        client,
        workspace_id,
        access_token,
        {
            "name": "Mock agent provider",
            "provider_type": "custom",
            "base_url": "https://mock-agent.example/v1",
        },
    )
    settings = {
        "tools": [
            {
                "name": "lookup_weather",
                "description": "Look up a city's weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                    "additionalProperties": False,
                },
                "mock_result": {"forecast": "mild"},
            }
        ],
    }

    result = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "BUILTIN_AGENT_APP",
            "settings": settings,
            "provider_id": provider.json()["id"],
            "model": "agent-model",
            "input": "What is the weather?",
        },
    )
    assert result.status_code == 422
    assert "invalid arguments for tool" in result.json()["detail"]
    await client.aclose()


@pytest.mark.asyncio
async def test_uploaded_output_trace_maps_retrieval_and_tool_fields() -> None:
    client, workspace_id, access_token = await signed_in_client()
    async with async_session_maker() as db:
        connectors_before = await db.scalar(
            select(func.count()).select_from(ConnectorProfile)
        )
        tests_before = await db.scalar(
            select(func.count())
            .select_from(ConnectorTest)
            .where(ConnectorTest.workspace_id == UUID(workspace_id))
        )
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": {
                "rows": [
                    {
                        "query": "Question",
                        "answer": "Answer",
                        "contexts": ["source chunk"],
                        "calls": [{"name": "lookup"}],
                        "latency": 23.5,
                        "input_tokens": 7,
                        "output_tokens": 4,
                    }
                ],
                "input_field": "query",
                "output_field": "answer",
                "retrieved_contexts_field": "contexts",
                "tool_calls_field": "calls",
                "latency_ms_field": "latency",
                "tokens_in_field": "input_tokens",
                "tokens_out_field": "output_tokens",
            },
            "input": "Question",
        },
    )
    assert response.status_code == 200, response.text
    trace = response.json()["trace"]
    assert trace["output"] == "Answer"
    assert trace["steps"]["retrieved_chunks"] == ["source chunk"]
    assert trace["steps"]["tool_calls"] == [{"name": "lookup"}]
    assert trace["latency_ms"] == 23.5
    assert trace["usage"] == {"tokens_in": 7, "tokens_out": 4}
    assert response.json()["preview"] == [
        {
            "query": "Question",
            "answer": "Answer",
            "contexts": ["source chunk"],
            "calls": [{"name": "lookup"}],
            "latency": 23.5,
            "input_tokens": 7,
            "output_tokens": 4,
        }
    ]
    assert "steps.retrieved_chunks" in response.json()["detected_fields"]
    assert "steps.tool_calls" in response.json()["detected_fields"]
    async with async_session_maker() as db:
        connectors_after = await db.scalar(
            select(func.count()).select_from(ConnectorProfile)
        )
        tests_after = await db.scalar(
            select(func.count())
            .select_from(ConnectorTest)
            .where(ConnectorTest.workspace_id == UUID(workspace_id))
        )
    assert connectors_after == connectors_before
    assert tests_after == tests_before
    await client.aclose()


@pytest.mark.asyncio
async def test_upload_outputs_test_and_save_accept_top_level_provider_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handle_provider_request(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={"data": [{"id": "test-model", "object": "model"}]},
            )
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        gateway,
        "client_factory",
        mock_provider_client(handle_provider_request),
    )
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    provider = await create_tested_provider(
        client,
        workspace_id,
        access_token,
        {
            "name": f"Upload test provider {uuid4()}",
            "provider_type": "custom",
            "base_url": "https://mock-provider.example/v1",
        },
    )
    assert provider.status_code == 201, provider.text
    provider_id = provider.json()["id"]
    headers = {"Authorization": f"Bearer {access_token}"}
    project = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json={"name": f"Upload test project {uuid4()}"},
    )
    assert project.status_code == 201, project.text

    settings = {
        "rows": [{"input": "sample input", "output": "sample output"}],
        "input_field": "input",
        "output_field": "output",
    }
    test_path = f"/api/v1/workspaces/{workspace_id}/connectors/test-call"
    test_call = await client.post(
        test_path,
        headers=headers,
        json={
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": settings,
            "provider_id": provider_id,
            "input": "sample input",
        },
    )
    assert test_call.status_code == 200, test_call.text
    assert test_call.json()["trace"]["output"] == "sample output"

    invalid_settings = await client.post(
        test_path,
        headers=headers,
        json={
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": {**settings, "provider_id": provider_id},
            "input": "sample input",
        },
    )
    assert invalid_settings.status_code == 422
    assert "Unsupported setting 'provider_id'" in invalid_settings.json()["detail"]
    assert "validation error for" not in invalid_settings.json()["detail"].lower()

    saved = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects/{project.json()['id']}/connectors",
        headers=headers,
        json={
            "entry_point_type": "UPLOAD_OUTPUTS",
            "settings": settings,
            "provider_id": provider_id,
            "test_call_id": test_call.json()["test_call_id"],
            "name": "Uploaded outputs",
        },
    )
    assert saved.status_code == 201, saved.text
    async with async_session_maker() as db:
        connector = await db.scalar(
            select(ConnectorProfile).where(
                ConnectorProfile.id == UUID(saved.json()["id"])
            )
        )
    assert connector is not None
    assert "provider_id" not in connector.settings
    stored_rows = connector.settings.get("rows")
    assert isinstance(stored_rows, list) and stored_rows
    assert isinstance(stored_rows[0], dict)
    assert "provider_id" not in stored_rows[0]
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_rate_limiter_queues_rpm_and_pauses_at_rpd() -> None:
    clock = [0.0]
    waits: list[float] = []

    async def advance(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += seconds

    limiter = ProviderRateLimiter(clock=lambda: clock[0], sleeper=advance)
    provider_id = uuid4()
    queue_positions = await asyncio.gather(
        *[limiter.wait_for_slot(provider_id, rpm=2, rpd=3) for _ in range(3)]
    )
    assert sorted(queue_positions) == [0, 0, 0]
    assert waits == [30.0, 30.0]
    with pytest.raises(DailyQuotaPaused):
        await limiter.wait_for_slot(provider_id, rpm=2, rpd=3)


@pytest.mark.asyncio
async def test_llm_gateway_falls_back_after_retryable_provider_failure() -> None:
    observed_hosts: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        observed_hosts.append(request.url.host)
        if request.url.host == "primary.example":
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-fallback",
                "object": "chat.completion",
                "created": 1,
                "model": "fallback-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Fallback answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 2,
                    "total_tokens": 6,
                },
            },
        )

    def provider(provider_id: UUID, name: str, base_url: str) -> ProviderConfig:
        return ProviderConfig(
            id=provider_id,
            workspace_id=uuid4(),
            name=name,
            provider_type="custom",
            base_url=base_url,
            api_key_encrypted=None,
            rpm=600,
            rpd=100_000,
            max_input_tokens=8192,
            max_output_tokens=2048,
            fallback_provider_ids=[],
        )

    primary = provider(uuid4(), "Primary", "https://primary.example/v1")
    fallback = provider(uuid4(), "Fallback", "https://fallback.example/v1")
    test_gateway = LLMGateway(
        rate_limiter=ProviderRateLimiter(),
        client_factory=mock_provider_client(handle_request),
    )
    result = await test_gateway.complete(
        [primary, fallback],
        model="fallback-model",
        messages=[{"role": "user", "content": "Test"}],
    )

    assert result.output == "Fallback answer"
    assert result.provider_id == fallback.id
    assert observed_hosts == ["primary.example", "fallback.example"]


@pytest.mark.asyncio
async def test_judge_rubric_version_increments_only_for_rubric_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.llm_gateway.settings.allowed_private_hosts",
        "localhost,host.docker.internal",
    )

    def handle_provider_request(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={"data": [{"id": "judge-model", "object": "model"}]},
            )
        return httpx.Response(
            200,
            json={
                "id": "judge-test",
                "object": "chat.completion",
                "created": 0,
                "model": "judge-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        gateway,
        "client_factory",
        mock_provider_client(handle_provider_request),
    )
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    provider_response = await create_tested_provider(
        client,
        workspace_id,
        access_token,
        {"name": "Judge provider", "provider_type": "ollama"},
    )
    assert provider_response.status_code == 201, provider_response.text
    project_response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json={"name": "Judge project"},
    )
    assert project_response.status_code == 201, project_response.text
    path = (
        f"/api/v1/workspaces/{workspace_id}/projects/"
        f"{project_response.json()['id']}/judge-profiles/dev"
    )
    profile = {
        "role": "dev",
        "provider_id": provider_response.json()["id"],
        "model": "judge-model",
        "rubric_prompt": "Score relevance.",
    }
    created = await client.put(path, headers=headers, json=profile)
    assert created.status_code == 200, created.text
    assert created.json()["rubric_version"] == 1

    updated_model = await client.put(
        path,
        headers=headers,
        json={**profile, "model": "another-model"},
    )
    assert updated_model.status_code == 200, updated_model.text
    assert updated_model.json()["rubric_version"] == 1

    updated_rubric = await client.put(
        path,
        headers=headers,
        json={**profile, "rubric_prompt": "Score relevance and accuracy."},
    )
    assert updated_rubric.status_code == 200, updated_rubric.text
    assert updated_rubric.json()["rubric_version"] == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_non_admin_cannot_test_private_http_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def engineer_role(*args: object, **kwargs: object) -> str:
        return "engineer"

    monkeypatch.setattr(phase2_router, "_workspace_role", engineer_role)
    client, workspace_id, access_token = await signed_in_client()
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "entry_point_type": "HTTP_ENDPOINT",
            "settings": {
                "url": "http://127.0.0.1:9999/test",
                "allow_private_targets": True,
            },
            "input": "sample",
        },
    )
    assert response.status_code == 422
    assert "Only workspace owners or admins" in response.json()["detail"]
    await client.aclose()


@pytest.mark.asyncio
async def test_private_http_endpoint_requires_explicit_admin_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def resolve_localhost(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [
            (
                2,
                1,
                6,
                "",
                ("127.0.0.1", 9999),
            )
        ]

    monkeypatch.setattr(connectors.socket, "getaddrinfo", resolve_localhost)
    with pytest.raises(
        ValueError,
        match="Private endpoints require explicit Admin authorization",
    ):
        await connectors._check_target_is_public(
            "http://localhost:9999/chat", allow_private_targets=False
        )

    await connectors._check_target_is_public(
        "http://localhost:9999/chat", allow_private_targets=True
    )


@pytest.mark.asyncio
async def test_admin_can_test_explicitly_approved_private_http_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def resolve_localhost(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [(2, 1, 6, "", ("127.0.0.1", 9999))]

    def client_factory(timeout: httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"output": "approved"})
            ),
            timeout=timeout,
            follow_redirects=False,
        )

    monkeypatch.setattr(connectors.socket, "getaddrinfo", resolve_localhost)
    monkeypatch.setattr(connectors, "make_http_client", client_factory)
    settings = connectors.HttpEndpointSettings(
        entry_point_type="HTTP_ENDPOINT",
        url="http://localhost:9999/chat",
        allow_private_targets=True,
    )
    result = await connectors._test_http_endpoint(
        settings=settings,
        input_text="sample",
        credentials={},
        user_role="admin",
        started=0,
        conversation_history=[],
    )

    assert result["raw_response"] == {"output": "approved"}


@pytest.mark.asyncio
async def test_unresolvable_http_endpoint_fails_safe_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolution(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        raise connectors.socket.gaierror("name resolution failed")

    monkeypatch.setattr(connectors.socket, "getaddrinfo", fail_resolution)
    with pytest.raises(
        ValueError,
        match="Endpoint host could not be resolved for safe validation",
    ):
        await connectors._check_target_is_public(
            "https://unresolvable.invalid/chat", allow_private_targets=True
        )


@pytest.mark.asyncio
async def test_phase2_routes_remain_workspace_scoped() -> None:
    owner_client, owner_workspace_id, owner_token = await signed_in_client()
    other_client, other_workspace_id, other_token = await signed_in_client()
    project = await owner_client.post(
        f"/api/v1/workspaces/{owner_workspace_id}/projects",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Private project"},
    )
    assert project.status_code == 201, project.text
    denied = await other_client.get(
        f"/api/v1/workspaces/{owner_workspace_id}/projects/{project.json()['id']}/connectors",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert denied.status_code == 403
    assert other_workspace_id != owner_workspace_id
    await owner_client.aclose()
    await other_client.aclose()


@pytest.mark.asyncio
async def test_chat_conversation_messages_are_owner_scoped() -> None:
    owner_client, workspace_id, owner_token = await signed_in_client()
    other_client, _, other_token = await signed_in_client()
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}
    other = await other_client.get("/api/v1/auth/me", headers=other_headers)
    async with async_session_maker() as db:
        db.add(
            WorkspaceMembership(
                user_id=UUID(other.json()["id"]),
                workspace_id=UUID(workspace_id),
                role="viewer",
            )
        )
        await db.commit()

    created = await owner_client.post(
        f"/api/v1/workspaces/{workspace_id}/chat/conversations",
        headers=owner_headers,
        json={"kind": "assistant", "title": "Setup help"},
    )
    assert created.status_code == 201, created.text
    conversation_id = UUID(created.json()["id"])
    async with async_session_maker() as db:
        db.add(
            ChatMessage(
                conversation_id=conversation_id,
                role="user",
                content="Where are providers configured?",
            )
        )
        await db.commit()

    own_messages = await owner_client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/conversations/{conversation_id}/messages",
        headers=owner_headers,
    )
    assert own_messages.status_code == 200
    assert own_messages.json()[0]["content"] == "Where are providers configured?"

    foreign_messages = await other_client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/conversations/{conversation_id}/messages",
        headers=other_headers,
    )
    foreign_rename = await other_client.patch(
        f"/api/v1/workspaces/{workspace_id}/chat/conversations/{conversation_id}",
        headers=other_headers,
        json={"title": "Stolen"},
    )
    foreign_delete = await other_client.delete(
        f"/api/v1/workspaces/{workspace_id}/chat/conversations/{conversation_id}",
        headers=other_headers,
    )
    assert foreign_messages.status_code == 404
    assert foreign_rename.status_code == 404
    assert foreign_delete.status_code == 404
    await owner_client.aclose()
    await other_client.aclose()


def test_chat_redaction_removes_bearer_password_and_provider_key_values() -> None:
    message = (
        "Authorization: Bearer eyJhbGciOiJfake-secret "
        "api_key=secret-value password:'hunter2' "
        "sk-123456789012345678901234"
    )

    redacted = redact_chat_text(message)

    for secret in (
        "eyJhbGciOiJfake-secret",
        "secret-value",
        "hunter2",
        "sk-123456789012345678901234",
    ):
        assert secret not in redacted
    assert redacted.count("[REDACTED]") == 4


def test_frontend_connector_allow_lists_match_all_backend_settings_models() -> None:
    fields_path = (
        Path(__file__).parents[2] / "frontend" / "src" / "connectorSettingsFields.json"
    )
    frontend_fields = json.loads(fields_path.read_text(encoding="utf-8"))

    assert set(frontend_fields) == set(CONNECTOR_SETTINGS_MODELS)
    for entry_point_type, settings_model in CONNECTOR_SETTINGS_MODELS.items():
        expected = set(settings_model.model_fields) - {"entry_point_type"}
        assert set(frontend_fields[entry_point_type]) == expected


@pytest.mark.asyncio
async def test_preferences_validate_default_provider_and_remember_project() -> None:
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    project = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json={"name": "Remembered project"},
    )
    assert project.status_code == 201, project.text

    async with async_session_maker() as db:
        provider = ProviderConfig(
            workspace_id=UUID(workspace_id),
            name="Workspace default",
            name_key="workspace default",
            provider_type="custom",
            base_url="https://provider.example/v1",
            test_model="test-model",
            api_key_encrypted=encrypt_secret("provider-secret-never-prompt"),
            rpm=10,
            rpd=100,
            max_input_tokens=4096,
            max_output_tokens=1024,
            fallback_provider_ids=[],
        )
        db.add(provider)
        await db.commit()
        provider_id = provider.id

    saved = await client.put(
        f"/api/v1/workspaces/{workspace_id}/preferences",
        headers=headers,
        json={
            "default_provider_id": str(provider_id),
            "active_project_id": project.json()["id"],
            "last_page": "connector",
            "last_entry_point": "UPLOAD_OUTPUTS",
            "last_column_mapping": {"input_field": "question"},
            "memory_message_count": 1,
            "memory_token_budget": 1024,
            "chat_retention_days": 30,
        },
    )
    assert saved.status_code == 200, saved.text
    preferences = await client.get(
        f"/api/v1/workspaces/{workspace_id}/preferences",
        headers=headers,
    )
    assert preferences.status_code == 200
    assert preferences.json()["default_provider_id"] == str(provider_id)
    assert preferences.json()["active_project_id"] == project.json()["id"]
    assert preferences.json()["last_page"] == "connector"
    assert preferences.json()["last_entry_point"] == "UPLOAD_OUTPUTS"
    assert preferences.json()["last_column_mapping"] == {"input_field": "question"}
    assert preferences.json()["memory_message_count"] == 1
    assert preferences.json()["chat_retention_days"] == 30

    other_client, other_workspace_id, other_token = await signed_in_client()
    async with async_session_maker() as db:
        other_provider = ProviderConfig(
            workspace_id=UUID(other_workspace_id),
            name="Other workspace provider",
            name_key="other workspace provider",
            provider_type="custom",
            base_url="https://other.example/v1",
            test_model="other-model",
            rpm=10,
            rpd=100,
            max_input_tokens=4096,
            max_output_tokens=1024,
            fallback_provider_ids=[],
        )
        db.add(other_provider)
        await db.commit()
        other_provider_id = other_provider.id
    rejected = await client.put(
        f"/api/v1/workspaces/{workspace_id}/preferences",
        headers=headers,
        json={"default_provider_id": str(other_provider_id)},
    )
    assert rejected.status_code == 422
    await client.aclose()
    await other_client.aclose()


@pytest.mark.asyncio
async def test_assistant_redacts_and_persists_chat_through_default_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    async with async_session_maker() as db:
        provider = ProviderConfig(
            workspace_id=UUID(workspace_id),
            name="Assistant provider",
            name_key="assistant provider",
            provider_type="custom",
            base_url="https://provider.example/v1",
            test_model="assistant-model",
            api_key_encrypted=encrypt_secret("provider-secret-never-prompt"),
            rpm=10,
            rpd=100,
            max_input_tokens=4096,
            max_output_tokens=1024,
            fallback_provider_ids=[],
        )
        db.add(provider)
        await db.commit()
        provider_id = provider.id

    preference = await client.put(
        f"/api/v1/workspaces/{workspace_id}/preferences",
        headers=headers,
        json={
            "default_provider_id": str(provider_id),
            "memory_message_count": 1,
        },
    )
    assert preference.status_code == 200, preference.text
    conversation = await client.post(
        f"/api/v1/workspaces/{workspace_id}/chat/conversations",
        headers=headers,
        json={"kind": "assistant"},
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    sent_messages: list[list[dict[str, object]]] = []

    async def mock_complete(
        providers: list[ProviderConfig],
        *,
        model: str,
        messages: list[dict[str, object]],
        temperature: float = 0,
        max_output_tokens: int | None = None,
    ) -> ChatResult:
        del temperature, max_output_tokens
        sent_messages.append(messages)
        output = (
            "A compact summary."
            if "Summarize this conversation memory" in str(messages[0]["content"])
            else "GreenLit evaluates saved applications."
        )
        return ChatResult(
            output=output,
            model=model,
            tokens_in=12,
            tokens_out=6,
            raw_response={},
            provider_id=providers[0].id,
            queue_position=0,
        )

    monkeypatch.setattr(gateway, "complete", mock_complete)
    first = await client.post(
        f"/api/v1/workspaces/{workspace_id}/assistant/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Remember api_key=prompt-secret"},
    )
    assert first.status_code == 200, first.text
    assert "prompt-secret" not in first.text
    assert "provider-secret-never-prompt" not in json.dumps(sent_messages)

    second = await client.post(
        f"/api/v1/workspaces/{workspace_id}/assistant/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "What does GreenLit evaluate?"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["memory"]["summary_used"] is True
    assert any(
        "Summarize this conversation memory" in str(messages[0]["content"])
        for messages in sent_messages
    )

    persisted = await client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/conversations/{conversation_id}/messages",
        headers=headers,
    )
    assert persisted.status_code == 200
    assert len(persisted.json()) == 4
    assert "prompt-secret" not in persisted.text
    await client.aclose()


@pytest.mark.asyncio
async def test_test_chat_drafts_are_pending_idempotent_and_preserve_prior_items() -> (
    None
):
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    created_project = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json={"name": "Chat draft project"},
    )
    assert created_project.status_code == 201, created_project.text
    project_id = UUID(created_project.json()["id"])
    async with async_session_maker() as db:
        user_id = await db.scalar(
            select(WorkspaceMembership.user_id).where(
                WorkspaceMembership.workspace_id == UUID(workspace_id)
            )
        )
        assert user_id is not None
        connector = ConnectorProfile(
            project_id=project_id,
            display_name="Prompt connector",
            name_key="prompt connector",
            entry_point_type="PROMPT_APP",
            settings={
                "entry_point_type": "PROMPT_APP",
                "system_prompt": "Answer helpfully",
            },
            content_hash="a" * 64,
            access_level="white-box",
        )
        db.add(connector)
        await db.flush()
        db.add(
            AppVersion(
                project_id=project_id,
                connector_profile_id=connector.id,
                version=1,
                content_hash="a" * 64,
                config_snapshot={},
                access_level="white-box",
            )
        )
        dataset = Dataset(
            project_id=project_id,
            name="Test Chat drafts",
            task_type="chatbot",
            created_by=user_id,
        )
        db.add(dataset)
        await db.flush()
        prior_version = DatasetVersion(
            dataset_id=dataset.id,
            version=1,
            content_hash="b" * 64,
            split_strategy="preserve",
        )
        db.add(prior_version)
        await db.flush()
        db.add(
            DatasetItem(
                dataset_version_id=prior_version.id,
                position=1,
                input_text="Existing approved input",
                reference_answer="Existing answer",
                category="normal",
                provenance="uploaded",
                review_status="approved",
                split="dev",
                data={},
            )
        )
        conversation = ChatConversation(
            owner_id=user_id,
            workspace_id=UUID(workspace_id),
            project_id=project_id,
            kind="project",
            title="Test session",
        )
        db.add(conversation)
        await db.flush()
        db.add_all(
            [
                ChatMessage(
                    conversation_id=conversation.id,
                    role="user",
                    content="What is GreenLit?",
                    created_at=datetime(2026, 1, 1),
                ),
                ChatMessage(
                    conversation_id=conversation.id,
                    role="assistant",
                    content="An application evaluation platform.",
                    trace={"steps": {"retrieved_chunks": ["chunk"]}},
                    created_at=datetime(2026, 1, 1, 0, 0, 1),
                ),
            ]
        )
        await db.commit()
        conversation_id = conversation.id

    path = (
        f"/api/v1/workspaces/{workspace_id}/projects/{project_id}"
        f"/test-chat/conversations/{conversation_id}/draft-items"
    )
    first = await client.post(path, headers=headers, json={})
    assert first.status_code == 200, first.text
    assert first.json()["created_items"] == 1
    assert first.json()["review_status"] == "pending"
    repeated = await client.post(path, headers=headers, json={})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["created_items"] == 0

    async with async_session_maker() as db:
        saved_dataset = await db.scalar(
            select(Dataset).where(
                Dataset.project_id == project_id,
                Dataset.name == "Test Chat drafts",
            )
        )
        assert saved_dataset is not None
        versions = list(
            await db.scalars(
                select(DatasetVersion)
                .where(DatasetVersion.dataset_id == saved_dataset.id)
                .order_by(DatasetVersion.version)
            )
        )
        assert [version.version for version in versions] == [1, 2]
        version_two_items = list(
            await db.scalars(
                select(DatasetItem)
                .where(DatasetItem.dataset_version_id == versions[1].id)
                .order_by(DatasetItem.position)
            )
        )
        assert len(version_two_items) == 2
        assert version_two_items[0].review_status == "approved"
        assert version_two_items[1].review_status == "pending"
        assert version_two_items[1].provenance == "chat-session"
        assert version_two_items[1].reference_answer == (
            "An application evaluation platform."
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_retention_removes_only_expired_owner_conversations() -> None:
    client, workspace_id, access_token = await signed_in_client()
    async with async_session_maker() as db:
        user_id = await db.scalar(
            select(WorkspaceMembership.user_id).where(
                WorkspaceMembership.workspace_id == UUID(workspace_id)
            )
        )
        assert user_id is not None
        expired = ChatConversation(
            owner_id=user_id,
            workspace_id=UUID(workspace_id),
            kind="assistant",
            title="Expired conversation",
            updated_at=datetime.utcnow() - timedelta(days=31),
        )
        recent = ChatConversation(
            owner_id=user_id,
            workspace_id=UUID(workspace_id),
            kind="assistant",
            title="Recent conversation",
        )
        db.add_all([expired, recent])
        await db.commit()
        expired_id = expired.id
        recent_id = recent.id

    listed = await client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/conversations",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert listed.status_code == 200, listed.text
    assert {item["id"] for item in listed.json()} == {str(recent_id)}
    async with async_session_maker() as db:
        assert await db.get(ChatConversation, expired_id) is None
        assert await db.get(ChatConversation, recent_id) is not None
    await client.aclose()
