from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import shlex
import socket
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from jsonschema import SchemaError as JsonSchemaSchemaError
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as validate_json_schema
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProviderConfig
from app.phase2_schemas import (
    BuiltinAgentSettings,
    BuiltinRagSettings,
    CliCommandSettings,
    DockerImageSettings,
    GitRepoSettings,
    HttpEndpointSettings,
    McpServerSettings,
    PromptAppSettings,
    ProxyModeSettings,
    UploadOutputsSettings,
    WebsiteUrlSettings,
)
from app.services.llm_gateway import ChatResult, LLMGateway, ProviderRequestError

_ENTRY_POINT_TYPES: tuple[dict[str, object], ...] = (
    {
        "type": "HTTP_ENDPOINT",
        "label": "HTTP endpoint",
        "description": "App running at a URL (staging or localhost)",
        "access_level": "black-box",
        "implemented": True,
        "coming_in": None,
    },
    {
        "type": "PYTHON_FUNCTION",
        "label": "Python function",
        "description": "A Python function (module:function)",
        "access_level": "white-box",
        "implemented": False,
        "coming_in": "Phase 2 (isolated execution required)",
    },
    {
        "type": "PYTHON_SDK_TRACED",
        "label": "Python SDK traced",
        "description": "A Python app instrumented with GreenLit tracing",
        "access_level": "white-box",
        "implemented": False,
        "coming_in": "Phase 2 (isolated execution required)",
    },
    {
        "type": "PROMPT_APP",
        "label": "Prompt App",
        "description": "No-code: system prompt + model",
        "access_level": "white-box",
        "implemented": True,
        "coming_in": None,
    },
    {
        "type": "BUILTIN_RAG_APP",
        "label": "Built-in RAG app",
        "description": "Built-in RAG app using supplied documents",
        "access_level": "white-box",
        "implemented": True,
        "coming_in": None,
    },
    {
        "type": "BUILTIN_AGENT_APP",
        "label": "Built-in agent",
        "description": "Built-in tool-using agent",
        "access_level": "white-box",
        "implemented": True,
        "coming_in": None,
    },
    {
        "type": "DOCKER_IMAGE",
        "label": "Docker image",
        "description": "Docker image or compose file",
        "access_level": "black-box",
        "implemented": False,
        "coming_in": "Phase 3 (real sandbox required)",
    },
    {
        "type": "GIT_REPO",
        "label": "Git repository",
        "description": "Git repository + entrypoint",
        "access_level": "white-box",
        "implemented": False,
        "coming_in": "Phase 3 (real sandbox required)",
    },
    {
        "type": "CLI_COMMAND",
        "label": "CLI command",
        "description": "Command-line program with an input template",
        "access_level": "black-box",
        "implemented": False,
        "coming_in": "Phase 3 (real sandbox required)",
    },
    {
        "type": "PROXY_MODE",
        "label": "Proxy mode",
        "description": "Point your app's LLM base URL at GreenLit",
        "access_level": "white-box",
        "implemented": False,
        "coming_in": "Phase 3 (real sandbox required)",
    },
    {
        "type": "UPLOAD_OUTPUTS",
        "label": "Upload outputs",
        "description": "Upload inputs and outputs that you already generated",
        "access_level": "black-box",
        "implemented": True,
        "coming_in": None,
    },
    {
        "type": "WEBSITE_URL",
        "label": "Website URL",
        "description": "Discover an embedded chatbot on a website",
        "access_level": "black-box",
        "implemented": False,
        "coming_in": "Phase 10 (manual browser verification required)",
    },
    {
        "type": "MCP_SERVER",
        "label": "MCP server",
        "description": "App or agent exposed over MCP",
        "access_level": "black-box",
        "implemented": False,
        "coming_in": "Phase 10 (manual MCP verification required)",
    },
)


def entry_point_types() -> list[dict[str, object]]:
    from app.phase2_schemas import CONNECTOR_SETTINGS_MODELS

    result: list[dict[str, object]] = []
    for entry_type in _ENTRY_POINT_TYPES:
        item = dict(entry_type)
        settings_model = CONNECTOR_SETTINGS_MODELS.get(str(item["type"]))
        item["settings_schema"] = (
            settings_model.model_json_schema() if settings_model else {}
        )
        result.append(item)
    return result


def validate_connector_settings(
    entry_point_type: str, settings: Mapping[str, object]
) -> tuple[BaseModel, dict[str, object]]:
    from app.phase2_schemas import CONNECTOR_SETTINGS_MODELS

    settings_model = CONNECTOR_SETTINGS_MODELS.get(entry_point_type)
    if settings_model is None:
        raise ValueError("This entry point type is coming in a later phase")
    metadata = next(
        item for item in _ENTRY_POINT_TYPES if item["type"] == entry_point_type
    )
    if not metadata["implemented"]:
        reason = {
            "PYTHON_FUNCTION": "a safe isolated execution runner",
            "PYTHON_SDK_TRACED": "a safe isolated execution runner",
            "DOCKER_IMAGE": "a verified real Docker sandbox runner",
            "GIT_REPO": "a verified real Git sandbox runner",
            "CLI_COMMAND": "a verified CLI sandbox runner",
            "PROXY_MODE": "a verified outbound request sandbox",
            "WEBSITE_URL": (
                "manual browser verification against the seeded demo website"
            ),
            "MCP_SERVER": "manual MCP runtime verification against a live server",
        }.get(entry_point_type, "a future release")
        raise ValueError(
            f"This entry point type is not available yet; it requires {reason}."
        )
    payload = dict(settings)
    payload["entry_point_type"] = entry_point_type
    try:
        validated = settings_model.model_validate(payload)
    except ValidationError as exc:
        messages: list[str] = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            if error["type"] == "extra_forbidden":
                messages.append(
                    f"Unsupported setting '{location}'. Remove it from settings."
                )
            elif error["type"] == "missing":
                messages.append(f"Missing required setting '{location}'.")
            else:
                messages.append(f"{location}: {error['msg']}")
        raise ValueError(
            "Invalid connector settings. " + " ".join(messages[:5])
        ) from exc
    normalized = validated.model_dump(mode="json", exclude={"entry_point_type"})
    return validated, normalized


def connector_content_hash(
    entry_point_type: str,
    settings: Mapping[str, object],
    credentials: Mapping[str, str],
    *,
    provider_id: UUID | None = None,
    model: str | None = None,
) -> str:
    secret_fingerprint = {
        key: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for key, value in sorted(credentials.items())
    }
    serialized = json.dumps(
        {
            "entry_point_type": entry_point_type,
            "settings": settings,
            "provider_id": str(provider_id) if provider_id else None,
            "model": model,
            "credentials_fingerprint": secret_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def provider_out(provider: ProviderConfig) -> dict[str, object]:
    return {
        "id": provider.id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "default_model": provider.test_model,
        "test_model": provider.test_model,
        "original_name": provider.original_name,
        "duplicate_of": str(provider.duplicate_of) if provider.duplicate_of else None,
        "is_duplicate": provider.duplicate_of is not None,
        "rpm": provider.rpm,
        "rpd": provider.rpd,
        "max_input_tokens": provider.max_input_tokens,
        "max_output_tokens": provider.max_output_tokens,
        "fallback_provider_ids": provider.fallback_provider_ids,
        "has_api_key": provider.api_key_encrypted is not None,
    }


async def get_provider_chain(
    db: AsyncSession, workspace_id: UUID, provider_id: UUID
) -> list[ProviderConfig]:
    provider = await db.scalar(
        select(ProviderConfig).where(
            ProviderConfig.id == provider_id,
            ProviderConfig.workspace_id == workspace_id,
        )
    )
    if provider is None:
        raise ValueError("Configured provider was not found in this workspace")
    chain = [provider]
    seen = {provider.id}
    pending_fallbacks = list(provider.fallback_provider_ids)
    while pending_fallbacks:
        fallback_id = pending_fallbacks.pop(0)
        fallback_uuid = UUID(fallback_id)
        if fallback_uuid in seen:
            raise ValueError("Provider fallback chain contains a cycle or duplicate")
        fallback = await db.scalar(
            select(ProviderConfig).where(
                ProviderConfig.id == fallback_uuid,
                ProviderConfig.workspace_id == workspace_id,
            )
        )
        if fallback is None:
            raise ValueError("Fallback provider was not found in this workspace")
        chain.append(fallback)
        seen.add(fallback_uuid)
        pending_fallbacks.extend(fallback.fallback_provider_ids)
    return chain


def redact_secrets(value: Any, credentials: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for secret in credentials.values():
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {key: redact_secrets(item, credentials) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item, credentials) for item in value]
    return value


def _mapped_value(value: object, path: str) -> object:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdecimal():
            index = int(part)
            if index >= len(current):
                raise ValueError(f"Configured response field '{path}' was not found")
            current = current[index]
        else:
            raise ValueError(f"Configured response field '{path}' was not found")
    return current


def _secret_headers(credentials: Mapping[str, str]) -> dict[str, str]:
    forbidden = {"host", "content-length", "connection", "transfer-encoding"}
    headers: dict[str, str] = {}
    for key, value in credentials.items():
        if (
            not key
            or "\r" in key
            or "\n" in key
            or "\r" in value
            or "\n" in value
            or key.lower() in forbidden
        ):
            raise ValueError("Credential header name or value is invalid")
        headers[key] = value
    return headers


async def _check_target_is_public(url: str, allow_private_targets: bool) -> None:
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "Endpoint URL must not contain credentials, query, or fragment"
        )
    host = parsed.hostname
    if host is None:
        raise ValueError("Endpoint URL must include a host")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError(
            "Endpoint host could not be resolved for safe validation"
        ) from exc
    if not addresses:
        raise ValueError("Endpoint host did not resolve to an address")

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                "Endpoint host resolved to an invalid address"
            ) from exc
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if ip.is_global:
            continue
        is_private_target = (
            (ip.is_private or ip.is_loopback)
            and not ip.is_link_local
            and not ip.is_reserved
            and not ip.is_multicast
            and not ip.is_unspecified
        )
        if allow_private_targets and is_private_target:
            continue
        raise ValueError(
            "Private endpoints require explicit Admin authorization. "
            "A workspace owner or admin must enable 'Allow private targets' "
            "for this connector."
        )


def _usage(
    result: ChatResult,
) -> dict[str, int | None]:
    return {"tokens_in": result.tokens_in, "tokens_out": result.tokens_out}


def make_http_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


def _application_history(
    history: Sequence[dict[str, str]], max_messages: int
) -> list[ChatCompletionMessageParam]:
    if max_messages <= 0:
        return []
    result: list[ChatCompletionMessageParam] = []
    for item in history[-max_messages:]:
        if item.get("role") == "user":
            result.append({"role": "user", "content": item["content"]})
        elif item.get("role") == "assistant":
            result.append({"role": "assistant", "content": item["content"]})
    return result


async def execute_test_call(
    *,
    entry_point_type: str,
    settings: BaseModel,
    provider_id: UUID | None,
    model: str | None,
    input_text: str,
    conversation_history: list[dict[str, str]] | None,
    credentials: Mapping[str, str],
    workspace_id: UUID,
    user_role: str,
    db: AsyncSession,
    gateway: LLMGateway,
) -> dict[str, object]:
    started = time.perf_counter()
    context_history = _application_history(
        conversation_history or [], int(getattr(settings, "context_messages", 0))
    )
    if isinstance(settings, HttpEndpointSettings):
        response = await _test_http_endpoint(
            settings,
            input_text,
            credentials,
            user_role,
            started,
            context_history,
        )
        response["context_sent"] = [
            *context_history,
            {"role": "user", "content": input_text},
        ]
        return response
    if isinstance(settings, PromptAppSettings):
        if provider_id is None:
            raise ValueError("Select a saved provider before testing this app")
        result = await _run_prompt_app(
            settings,
            input_text,
            provider_id,
            model,
            context_history,
            workspace_id,
            db,
            gateway,
        )
        response = _trace_response(
            result.output,
            started,
            result.raw_response,
            usage=_usage(result),
            model=f"{result.provider_id}/{result.model}",
            extras={"steps": {"prompt_sent": settings.system_prompt}},
            credentials=credentials,
        )
        response["context_sent"] = [
            {"role": "system", "content": settings.system_prompt},
            *context_history,
            {"role": "user", "content": input_text},
        ]
        return response
    if isinstance(settings, BuiltinRagSettings):
        if provider_id is None:
            raise ValueError("Select a saved provider before testing this app")
        result, chunks, prompt = await _run_rag(
            settings,
            input_text,
            provider_id,
            model,
            context_history,
            workspace_id,
            db,
            gateway,
        )
        response = _trace_response(
            result.output,
            started,
            result.raw_response,
            usage=_usage(result),
            model=f"{result.provider_id}/{result.model}",
            extras={
                "steps": {
                    "prompt_sent": prompt,
                    "retrieved_chunks": chunks,
                }
            },
            credentials=credentials,
        )
        response["context_sent"] = [
            {"role": "system", "content": prompt},
            *context_history,
            {"role": "user", "content": input_text},
        ]
        return response
    if isinstance(settings, BuiltinAgentSettings):
        if provider_id is None:
            raise ValueError("Select a saved provider before testing this app")
        result, calls, prompt = await _run_agent(
            settings,
            input_text,
            provider_id,
            model,
            context_history,
            workspace_id,
            db,
            gateway,
        )
        response = _trace_response(
            result.output,
            started,
            result.raw_response,
            usage=_usage(result),
            model=f"{result.provider_id}/{result.model}",
            extras={
                "steps": {
                    "prompt_sent": prompt,
                    "tool_calls": calls,
                }
            },
            credentials=credentials,
        )
        response["context_sent"] = [
            {"role": "system", "content": prompt},
            *context_history,
            {"role": "user", "content": input_text},
        ]
        return response
    if isinstance(settings, DockerImageSettings):
        return await _test_docker_image(settings, input_text, started)
    if isinstance(settings, GitRepoSettings):
        return await _test_git_repo(settings, input_text, started)
    if isinstance(settings, CliCommandSettings):
        return await _test_cli_command(settings, input_text, started)
    if isinstance(settings, ProxyModeSettings):
        response = await _test_proxy_mode(
            settings, input_text, credentials, started, model or "proxy-model"
        )
        response["context_sent"] = [
            *context_history,
            {"role": "user", "content": input_text},
        ]
        return response
    if isinstance(settings, UploadOutputsSettings):
        return _test_uploaded_output(settings, input_text, started)
    if isinstance(settings, WebsiteUrlSettings):
        return await _test_website_url(settings, input_text, credentials, started)
    if isinstance(settings, McpServerSettings):
        return await _test_mcp_server(settings, input_text, started)
    raise ValueError("This entry point type is not available for test calls")


def _run_sandbox_command(
    argv: list[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ProviderRequestError(
            "Sandboxed command execution failed",
            retryable=False,
        ) from exc


async def _test_docker_image(
    settings: DockerImageSettings,
    input_text: str,
    started: float,
) -> dict[str, object]:
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        str(settings.cpus),
        "--memory",
        f"{settings.memory_mb}m",
        "--workdir",
        settings.working_directory,
    ]
    if settings.env:
        for item in settings.env:
            argv.extend(["-e", item])
    argv.append(settings.image)
    if settings.command:
        argv.extend(shlex.split(settings.command))
    elif input_text:
        argv.append(input_text)
    completed = await asyncio.to_thread(
        _run_sandbox_command,
        argv,
        timeout_seconds=settings.timeout_seconds,
        input_text=None,
    )
    if completed.returncode != 0:
        raise ProviderRequestError(
            f"Docker container exited with code {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}",
            retryable=False,
        )
    payload = {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
    return _trace_response(
        completed.stdout.strip() or input_text,
        started,
        payload,
        extras={
            "steps": {
                "tool_calls": [
                    {
                        "name": settings.image,
                        "args": {"command": settings.command or input_text},
                        "result": payload,
                        "error": None,
                    }
                ]
            }
        },
    )


async def _test_git_repo(
    settings: GitRepoSettings,
    input_text: str,
    started: float,
) -> dict[str, object]:
    clone_dir = tempfile.mkdtemp(prefix="greenlit-git-")
    argv = [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        settings.branch,
        settings.repo_url,
        clone_dir,
    ]
    completed = await asyncio.to_thread(
        _run_sandbox_command,
        argv,
        timeout_seconds=settings.timeout_seconds,
        cwd=None,
    )
    if completed.returncode != 0:
        raise ProviderRequestError(
            f"Git clone failed: {completed.stderr.strip() or completed.stdout.strip()}",
            retryable=False,
        )
    if settings.command:
        entry = shlex.split(settings.command)
    else:
        entry = ["python", "-c", f"print({json.dumps(input_text)})"]
    result = await asyncio.to_thread(
        _run_sandbox_command,
        entry,
        cwd=clone_dir,
        timeout_seconds=settings.timeout_seconds,
        input_text=input_text,
    )
    if result.returncode != 0:
        raise ProviderRequestError(
            "Git repo command failed: "
            f"{result.stderr.strip() or result.stdout.strip()}",
            retryable=False,
        )
    payload = {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
    return _trace_response(
        result.stdout.strip() or input_text,
        started,
        payload,
        extras={
            "steps": {
                "tool_calls": [
                    {
                        "name": settings.repo_url,
                        "args": {"command": settings.command or entry},
                        "result": payload,
                        "error": None,
                    }
                ]
            }
        },
    )


async def _test_cli_command(
    settings: CliCommandSettings,
    input_text: str,
    started: float,
) -> dict[str, object]:
    command = shlex.split(settings.command)
    cwd = settings.working_directory or None
    completed = await asyncio.to_thread(
        _run_sandbox_command,
        command,
        cwd=cwd,
        timeout_seconds=settings.timeout_seconds,
        input_text=input_text,
    )
    if completed.returncode != 0:
        raise ProviderRequestError(
            f"CLI command exited with code {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}",
            retryable=False,
        )
    payload = {
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
    return _trace_response(
        completed.stdout.strip() or input_text,
        started,
        payload,
        extras={
            "steps": {
                "tool_calls": [
                    {
                        "name": settings.command,
                        "args": {"input": input_text},
                        "result": payload,
                        "error": None,
                    }
                ]
            }
        },
    )


def _render_proxy_body(template: str, model: str, input_text: str) -> dict[str, object]:
    rendered = template
    for token, value in (("{{model}}", model), ("{{input}}", input_text)):
        rendered = rendered.replace(token, json.dumps(value, ensure_ascii=False)[1:-1])
    try:
        payload = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise ValueError("Proxy request template must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Proxy request template must decode to a JSON object")
    return payload


async def _test_proxy_mode(
    settings: ProxyModeSettings,
    input_text: str,
    credentials: Mapping[str, str],
    started: float,
    model: str,
) -> dict[str, object]:
    url = str(settings.base_url)
    await _check_target_is_public(
        url, allow_private_targets=settings.allow_private_targets
    )
    headers = {"Content-Type": "application/json"}
    if credentials:
        headers.update({key: value for key, value in credentials.items()})
    body = _render_proxy_body(
        settings.request_body_template,
        model=model,
        input_text=input_text,
    )
    timeout = httpx.Timeout(settings.timeout_seconds)
    try:
        async with make_http_client(timeout) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise ProviderRequestError(
            "Proxy test call timed out",
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderRequestError(
            "Could not connect to the configured proxy target",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        raise ProviderRequestError(
            f"Proxy target returned HTTP {response.status_code}",
            retryable=response.status_code in {429, 500, 502, 503, 504},
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text}
    output = payload.get("output") if isinstance(payload, dict) else payload
    return _trace_response(
        output,
        started,
        payload,
        extras={
            "steps": {
                "tool_calls": [
                    {
                        "name": "proxy",
                        "args": {"url": url, "input": input_text},
                        "result": payload,
                        "error": None,
                    }
                ]
            }
        },
        credentials=credentials,
    )


async def _test_http_endpoint(
    settings: HttpEndpointSettings,
    input_text: str,
    credentials: Mapping[str, str],
    user_role: str,
    started: float,
    conversation_history: list[ChatCompletionMessageParam],
) -> dict[str, object]:
    if settings.allow_private_targets and user_role not in {"owner", "admin"}:
        raise ValueError(
            "Only workspace owners or admins may authorize private endpoint access"
        )
    url = str(settings.url)
    await _check_target_is_public(url, settings.allow_private_targets)
    headers = _secret_headers(credentials)
    timeout = httpx.Timeout(settings.timeout_seconds)
    try:
        async with make_http_client(timeout) as client:
            if settings.method == "GET":
                response = await client.get(
                    url,
                    params={settings.input_field: input_text},
                    headers=headers,
                )
            else:
                template = settings.request_body_template
                rendered = template.replace("{{input}}", json.dumps(input_text))
                rendered = rendered.replace(
                    "{{history}}", json.dumps(conversation_history)
                )
                body = json.loads(rendered)
                response = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise ProviderRequestError(
            "Endpoint test call timed out", retryable=True
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderRequestError(
            "Could not connect to the configured endpoint", retryable=True
        ) from exc
    if response.status_code >= 300:
        raise ProviderRequestError(
            f"Endpoint returned HTTP {response.status_code}",
            retryable=response.status_code == 429 or response.status_code >= 500,
        )
    if len(response.content) > 2_000_000:
        raise ValueError("Endpoint response exceeds the 2 MB test-call limit")
    try:
        raw_response: object = response.json()
    except ValueError:
        raw_response = response.text
    output = (
        _mapped_value(raw_response, settings.output_field)
        if isinstance(raw_response, dict | list)
        else raw_response
    )
    return _trace_response(
        output,
        started,
        raw_response,
        credentials=credentials,
    )


async def _run_prompt_app(
    settings: PromptAppSettings,
    input_text: str,
    provider_id: UUID,
    model: str | None,
    conversation_history: list[ChatCompletionMessageParam],
    workspace_id: UUID,
    db: AsyncSession,
    gateway: LLMGateway,
) -> ChatResult:
    providers = await get_provider_chain(db, workspace_id, provider_id)
    result = await gateway.complete(
        providers,
        model=model,
        messages=[
            {"role": "system", "content": settings.system_prompt},
            *conversation_history,
            {"role": "user", "content": input_text},
        ],
        temperature=settings.temperature,
    )
    if settings.output_json_schema is not None:
        try:
            parsed = json.loads(result.output)
            validate_json_schema(parsed, settings.output_json_schema)
        except (
            json.JSONDecodeError,
            JsonSchemaValidationError,
            JsonSchemaSchemaError,
        ) as exc:
            raise ValueError(
                "Model output did not match the configured JSON schema"
            ) from exc
    return result


def _split_chunks(
    title: str, text: str, chunk_size: int, overlap: int
) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(
            {
                "text": text[start:end],
                "source": title,
                "score": 0.0,
            }
        )
        if end == len(text):
            break
        start = end - overlap
    return chunks


async def _run_rag(
    settings: BuiltinRagSettings,
    input_text: str,
    provider_id: UUID,
    model: str | None,
    conversation_history: list[ChatCompletionMessageParam],
    workspace_id: UUID,
    db: AsyncSession,
    gateway: LLMGateway,
) -> tuple[ChatResult, list[dict[str, object]], str]:
    chunks = [
        chunk
        for document in settings.documents
        for chunk in _split_chunks(
            document.title,
            document.text,
            settings.chunk_size,
            settings.chunk_overlap,
        )
    ]
    query_terms = set(re.findall(r"\w+", input_text.lower()))
    ranked: list[tuple[int, dict[str, object]]] = []
    for chunk in chunks:
        chunk_terms = set(re.findall(r"\w+", str(chunk["text"]).lower()))
        overlap = len(query_terms & chunk_terms)
        ranked.append((overlap, {**chunk, "score": overlap}))
    ranked.sort(key=lambda item: item[0], reverse=True)
    retrieved = [chunk for _, chunk in ranked[: settings.top_k]]
    context = "\n\n".join(
        f"[{chunk['source']}]\n{chunk['text']}" for chunk in retrieved
    )
    prompt = f"{settings.prompt}\n\nContext:\n{context}"
    providers = await get_provider_chain(db, workspace_id, provider_id)
    result = await gateway.complete(
        providers,
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            *conversation_history,
            {"role": "user", "content": input_text},
        ],
        temperature=settings.temperature,
    )
    return result, retrieved, prompt


async def _run_agent(
    settings: BuiltinAgentSettings,
    input_text: str,
    provider_id: UUID,
    model: str | None,
    conversation_history: list[ChatCompletionMessageParam],
    workspace_id: UUID,
    db: AsyncSession,
    gateway: LLMGateway,
) -> tuple[ChatResult, list[dict[str, object]], str]:
    providers = await get_provider_chain(db, workspace_id, provider_id)
    available_tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in settings.tools
    ]
    prompt = (
        settings.system_prompt
        + "\nUse a tool only when needed. To call one, respond with JSON "
        '{"tool":"name","arguments":{...}}. Otherwise answer normally.\n'
        + f"Available tools: {json.dumps(available_tools)}"
    )
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": prompt},
        *conversation_history,
        {"role": "user", "content": input_text},
    ]
    calls: list[dict[str, object]] = []
    result: ChatResult | None = None
    tool_map = {tool.name: tool for tool in settings.tools}
    for _ in range(settings.max_steps):
        result = await gateway.complete(
            providers,
            model=model,
            messages=messages,
            temperature=settings.temperature,
        )
        try:
            candidate = json.loads(result.output)
        except json.JSONDecodeError:
            break
        if not isinstance(candidate, dict) or "tool" not in candidate:
            break
        name = candidate.get("tool")
        arguments = candidate.get("arguments", {})
        if not isinstance(name, str) or name not in tool_map:
            raise ValueError("Model requested a tool that is not configured")
        if not isinstance(arguments, dict):
            raise ValueError("Model tool arguments must be a JSON object")
        tool = tool_map[name]
        if tool.parameters:
            try:
                validate_json_schema(arguments, tool.parameters)
            except (
                JsonSchemaValidationError,
                JsonSchemaSchemaError,
            ) as exc:
                raise ValueError(
                    f"Model returned invalid arguments for tool '{name}'"
                ) from exc
        calls.append(
            {
                "name": name,
                "args": arguments,
                "result": dict(tool.mock_result),
                "error": None,
            }
        )
        messages.extend(
            [
                {"role": "assistant", "content": result.output},
                {
                    "role": "user",
                    "content": "Mock tool result: " + json.dumps(tool.mock_result),
                },
            ]
        )
    if result is None:
        raise ProviderRequestError("The configured agent has no available provider")
    return result, calls, prompt


def _test_uploaded_output(
    settings: UploadOutputsSettings,
    input_text: str,
    started: float,
) -> dict[str, object]:
    if not input_text.strip():
        raise ValueError("Enter a non-empty sample input before testing")
    if not settings.rows:
        raise ValueError("Upload a CSV, JSON, or JSONL file before testing")
    fields = set(settings.rows[0])
    for uploaded_row in settings.rows[1:]:
        fields.intersection_update(uploaded_row)
    required_fields = {settings.input_field, settings.output_field}
    missing_fields = sorted(required_fields - fields)
    optional_fields = (
        settings.retrieved_contexts_field,
        settings.tool_calls_field,
        settings.latency_ms_field,
        settings.tokens_in_field,
        settings.tokens_out_field,
    )
    missing_fields.extend(
        sorted(field for field in optional_fields if field and field not in fields)
    )
    if missing_fields:
        raise ValueError(
            "Mapped columns are missing from the uploaded file: "
            + ", ".join(missing_fields)
        )

    def normalize_sample(value: object) -> str:
        normalized = str(value).strip()
        if (
            len(normalized) >= 2
            and normalized[0] == normalized[-1]
            and normalized[0] in {"'", '"'}
        ):
            normalized = normalized[1:-1].strip()
        return re.sub(r"\s+", " ", normalized).casefold()

    normalized_input = normalize_sample(input_text)
    if not normalized_input:
        raise ValueError("Enter a non-empty sample input before testing")
    row = next(
        (
            uploaded_row
            for uploaded_row in settings.rows
            if normalize_sample(uploaded_row.get(settings.input_field, ""))
            == normalized_input
        ),
        None,
    )
    if row is None:
        raise ValueError("No uploaded row matches the sample input")
    output = row[settings.output_field]
    contexts = (
        row[settings.retrieved_contexts_field]
        if settings.retrieved_contexts_field
        else None
    )
    tool_calls = row[settings.tool_calls_field] if settings.tool_calls_field else None
    steps: dict[str, object] = {}
    if contexts is not None:
        steps["retrieved_chunks"] = contexts
    if tool_calls is not None:
        steps["tool_calls"] = tool_calls
    usage: dict[str, int | None] = {"tokens_in": None, "tokens_out": None}
    for key, field in (
        ("tokens_in", settings.tokens_in_field),
        ("tokens_out", settings.tokens_out_field),
    ):
        if field and str(row[field]).strip():
            try:
                usage[key] = int(str(row[field]))
            except ValueError as exc:
                raise ValueError(
                    f"Mapped {field} value must be a whole number"
                ) from exc
    extras: dict[str, object] = {"steps": steps}
    if settings.latency_ms_field:
        try:
            latency_ms = float(str(row[settings.latency_ms_field]))
        except ValueError as exc:
            raise ValueError(
                f"Mapped {settings.latency_ms_field} value must be numeric"
            ) from exc
        if latency_ms < 0:
            raise ValueError("Mapped latency_ms value cannot be negative")
        extras["latency_ms"] = latency_ms
    result = _trace_response(
        output,
        started,
        row,
        usage=usage,
        extras=extras,
    )
    result["preview"] = settings.rows[:3]
    return result


async def _test_website_url(
    settings: WebsiteUrlSettings,
    input_text: str,
    credentials: Mapping[str, str],
    started: float,
) -> dict[str, object]:
    if not settings.authorized:
        raise ValueError("Website URL discovery requires explicit authorization")
    url = str(settings.url)
    parsed = urlsplit(url)
    if parsed.hostname is None:
        raise ValueError("Website URL must include a host")
    await _check_target_is_public(url, allow_private_targets=False)
    headers = _secret_headers(credentials)
    async with make_http_client(httpx.Timeout(settings.timeout_seconds)) as client:
        response = await client.get(url, headers=headers)
    if response.status_code >= 400:
        raise ProviderRequestError(
            f"Website URL returned HTTP {response.status_code}",
            retryable=response.status_code in {429, 500, 502, 503, 504},
        )
    title = ""
    match = re.search(r"<title>(.*?)</title>", response.text, re.I | re.S)
    if match is not None:
        title = match.group(1)
    payload = {
        "url": url,
        "input": input_text,
        "title": title,
        "status_code": response.status_code,
        "request_cap": settings.request_cap,
    }
    return _trace_response(
        f"Discovered website: {title or url}",
        started,
        payload,
        extras={
            "steps": {
                "retrieved_chunks": [
                    {
                        "source": url,
                        "text": response.text[:1000],
                        "score": 1.0,
                    }
                ],
                "tool_calls": [
                    {
                        "name": "discover_website",
                        "args": {"url": url},
                        "result": payload,
                        "error": None,
                    }
                ],
            }
        },
        credentials=credentials,
    )


async def _test_mcp_server(
    settings: McpServerSettings,
    input_text: str,
    started: float,
) -> dict[str, object]:
    if settings.server_url is None and not settings.command:
        raise ValueError("Either server_url or command must be provided")
    if settings.command:
        argv = shlex.split(settings.command)
        try:
            completed = subprocess.run(
                argv + [input_text],
                capture_output=True,
                text=True,
                timeout=settings.timeout_seconds,
                check=False,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise ProviderRequestError(
                "MCP command failed to execute",
                retryable=False,
            ) from exc
        if completed.returncode != 0:
            raise ProviderRequestError(
                f"MCP command exited with code {completed.returncode}: "
                f"{completed.stderr.strip() or completed.stdout.strip()}",
                retryable=False,
            )
        payload = {
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "returncode": completed.returncode,
        }
        return _trace_response(
            completed.stdout.strip() or input_text,
            started,
            payload,
            extras={
                "steps": {
                    "tool_calls": [
                        {
                            "name": settings.tool_name,
                            "args": {"input": input_text},
                            "result": payload,
                            "error": None,
                        }
                    ]
                }
            },
        )
    if settings.server_url is not None:
        async with make_http_client(httpx.Timeout(settings.timeout_seconds)) as client:
            response = await client.post(
                str(settings.server_url),
                json={
                    "tool": settings.tool_name,
                    "input": input_text,
                    "prompt_template": settings.prompt_template,
                },
                headers={"Content-Type": "application/json"},
            )
        if response.status_code >= 400:
            raise ProviderRequestError(
                f"MCP endpoint returned HTTP {response.status_code}",
                retryable=response.status_code in {429, 500, 502, 503, 504},
            )
        payload = response.json() if response.content else {"status": "ok"}
        return _trace_response(
            payload.get("output", payload),
            started,
            payload,
            extras={
                "steps": {
                    "tool_calls": [
                        {
                            "name": settings.tool_name,
                            "args": {"input": input_text},
                            "result": payload,
                            "error": None,
                        }
                    ]
                }
            },
        )
    raise ValueError("MCP server configuration is incomplete")


def _trace_response(
    output: object,
    started: float,
    raw_response: object,
    *,
    usage: Mapping[str, int | None] | None = None,
    model: str | None = None,
    extras: Mapping[str, object] | None = None,
    credentials: Mapping[str, str] | None = None,
) -> dict[str, object]:
    trace_steps: dict[str, object] = {}
    trace_usage: dict[str, int | None] = dict(
        usage or {"tokens_in": None, "tokens_out": None}
    )
    trace: dict[str, object] = {
        "output": output,
        "steps": trace_steps,
        "usage": trace_usage,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "model_used": model,
    }
    if extras:
        for key, value in extras.items():
            existing = trace.get(key)
            if isinstance(existing, dict) and isinstance(value, Mapping):
                trace[key] = {**existing, **value}
                if key == "steps":
                    trace_steps.update(value)
            else:
                trace[key] = value
                if key == "steps" and isinstance(value, dict):
                    trace_steps.update(value)
    missing = [
        name
        for name, value in (
            ("steps.retrieved_chunks", trace_steps.get("retrieved_chunks")),
            ("steps.tool_calls", trace_steps.get("tool_calls")),
            ("usage.tokens_in", trace_usage.get("tokens_in")),
            ("usage.tokens_out", trace_usage.get("tokens_out")),
            ("model_used", trace.get("model_used")),
        )
        if value is None
    ]
    sanitized_trace = redact_secrets(trace, credentials or {})
    sanitized_response = redact_secrets(raw_response, credentials or {})
    return {
        "trace": sanitized_trace,
        "raw_response": sanitized_response,
        "latency_ms": trace["latency_ms"],
        "detected_fields": [
            "output",
            "latency_ms",
            *(
                f"steps.{name}"
                for name, value in trace_steps.items()
                if value is not None
            ),
            *(
                f"usage.{name}"
                for name, value in trace_usage.items()
                if value is not None
            ),
            *(["model_used"] if trace.get("model_used") is not None else []),
        ],
        "missing_fields": missing,
    }
