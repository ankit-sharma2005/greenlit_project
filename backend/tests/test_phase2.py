from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import Base, async_session_maker, engine
from app.main import app
from app.models import ConnectorProfile, ProviderConfig
from app.routers import phase2 as phase2_router
from app.routers.phase2 import gateway
from app.services import connectors
from app.services.llm_gateway import LLMGateway
from app.services.rate_limit import DailyQuotaPaused, ProviderRateLimiter
from app.services.secrets import decrypt_secret


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
    observed_authorization: list[str] = []

    def handle_provider_request(request: httpx.Request) -> httpx.Response:
        observed_authorization.append(request.headers.get("authorization", ""))
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"id": "greenlit-test-model", "object": "model"}],
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

    github = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers",
        headers=headers,
        json={
            "name": "GitHub Models",
            "provider_type": "github_models",
            "api_key": github_secret,
        },
    )
    assert github.status_code == 201, github.text
    github_provider_id = github.json()["id"]

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

    ollama = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers",
        headers=headers,
        json={"name": "Local Ollama", "provider_type": "ollama"},
    )
    assert ollama.status_code == 201, ollama.text
    ollama_test = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers/"
        f"{ollama.json()['id']}/test-connection",
        headers=headers,
    )
    assert ollama_test.status_code == 200, ollama_test.text
    assert len(observed_authorization) == 2

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
    assert types[6]["coming_in"] == "phase 9"
    assert types[12]["coming_in"] == "phase 10"

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
    headers = {"Authorization": f"Bearer {access_token}"}
    provider = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers",
        headers=headers,
        json={
            "name": "Mock chat provider",
            "provider_type": "custom",
            "base_url": "https://mock-provider.example/v1",
            "api_key": "phase2-provider-secret",
        },
    )
    assert provider.status_code == 201, provider.text

    project = await client.post(
        f"/api/v1/workspaces/{workspace_id}/projects",
        headers=headers,
        json={"name": "Prompt project", "description": "Phase 2 integration test"},
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    prompt_settings = {
        "provider_id": provider.json()["id"],
        "model": "greenlit-model",
        "system_prompt": "Answer accurately.",
        "temperature": 0,
    }
    prompt_call = await client.post(
        f"/api/v1/workspaces/{workspace_id}/connectors/test-call",
        headers=headers,
        json={
            "entry_point_type": "PROMPT_APP",
            "settings": prompt_settings,
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
            "settings": {**prompt_settings, "model": "different-model"},
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
            "test_call_id": prompt_result["test_call_id"],
        },
    )
    assert saved_prompt.status_code == 201, saved_prompt.text
    assert saved_prompt.json()["app_version"] == 2

    rag_settings = {
        "provider_id": provider.json()["id"],
        "model": "greenlit-model",
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
) -> None:
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
async def test_judge_rubric_version_increments_only_for_rubric_changes() -> None:
    client, workspace_id, access_token = await signed_in_client()
    headers = {"Authorization": f"Bearer {access_token}"}
    provider_response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/providers",
        headers=headers,
        json={"name": "Judge provider", "provider_type": "ollama"},
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
    assert "Only workspace Admins" in response.json()["detail"]
    await client.aclose()


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
