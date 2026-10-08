from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
import time
from collections.abc import Mapping
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
    HttpEndpointSettings,
    PromptAppSettings,
    UploadOutputsSettings,
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
        "coming_in": "phase 9",
    },
    {
        "type": "GIT_REPO",
        "label": "Git repository",
        "description": "Git repository + entrypoint",
        "access_level": "white-box",
        "implemented": False,
        "coming_in": "phase 9",
    },
    {
        "type": "CLI_COMMAND",
        "label": "CLI command",
        "description": "Command-line program with an input template",
        "access_level": "black-box",
        "implemented": False,
        "coming_in": "phase 9",
    },
    {
        "type": "PROXY_MODE",
        "label": "Proxy mode",
        "description": "Point your app's LLM base URL at GreenLit",
        "access_level": "white-box",
        "implemented": False,
        "coming_in": "phase 9",
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
        "coming_in": "phase 10",
    },
    {
        "type": "MCP_SERVER",
        "label": "MCP server",
        "description": "App or agent exposed over MCP",
        "access_level": "black-box",
        "implemented": False,
        "coming_in": "phase 10",
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
        raise ValueError("Python entry points require the isolated execution runner")
    payload = dict(settings)
    payload["entry_point_type"] = entry_point_type
    try:
        validated = settings_model.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    normalized = validated.model_dump(mode="json", exclude={"entry_point_type"})
    return validated, normalized


def connector_content_hash(
    entry_point_type: str,
    settings: Mapping[str, object],
    credentials: Mapping[str, str],
) -> str:
    secret_fingerprint = {
        key: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for key, value in sorted(credentials.items())
    }
    serialized = json.dumps(
        {
            "entry_point_type": entry_point_type,
            "settings": settings,
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
    if allow_private_targets:
        return
    host = parsed.hostname
    if host is None:
        raise ValueError("Endpoint URL must include a host")
    if host.lower() == "localhost":
        raise ValueError("Private endpoints require explicit Admin authorization")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, host, parsed.port or 443, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValueError("Endpoint host could not be resolved") from exc
    if not addresses:
        raise ValueError("Endpoint host could not be resolved")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Private endpoints require explicit Admin authorization")


def _usage(
    result: ChatResult,
) -> dict[str, int | None]:
    return {"tokens_in": result.tokens_in, "tokens_out": result.tokens_out}


def make_http_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


async def execute_test_call(
    *,
    entry_point_type: str,
    settings: BaseModel,
    input_text: str,
    credentials: Mapping[str, str],
    workspace_id: UUID,
    user_role: str,
    db: AsyncSession,
    gateway: LLMGateway,
) -> dict[str, object]:
    started = time.perf_counter()
    if isinstance(settings, HttpEndpointSettings):
        return await _test_http_endpoint(
            settings, input_text, credentials, user_role, started
        )
    if isinstance(settings, PromptAppSettings):
        result = await _run_prompt_app(settings, input_text, workspace_id, db, gateway)
        return _trace_response(
            result.output,
            started,
            result.raw_response,
            usage=_usage(result),
            model=f"{result.provider_id}/{result.model}",
            extras={"steps": {"prompt_sent": settings.system_prompt}},
            credentials=credentials,
        )
    if isinstance(settings, BuiltinRagSettings):
        result, chunks, prompt = await _run_rag(
            settings, input_text, workspace_id, db, gateway
        )
        return _trace_response(
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
    if isinstance(settings, BuiltinAgentSettings):
        result, calls, prompt = await _run_agent(
            settings, input_text, workspace_id, db, gateway
        )
        return _trace_response(
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
    if isinstance(settings, UploadOutputsSettings):
        return _test_uploaded_output(settings, input_text, started)
    raise ValueError("This entry point type is not available for test calls")


async def _test_http_endpoint(
    settings: HttpEndpointSettings,
    input_text: str,
    credentials: Mapping[str, str],
    user_role: str,
    started: float,
) -> dict[str, object]:
    if settings.allow_private_targets and user_role not in {"owner", "admin"}:
        raise ValueError("Only workspace Admins may test private endpoints")
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
    workspace_id: UUID,
    db: AsyncSession,
    gateway: LLMGateway,
) -> ChatResult:
    providers = await get_provider_chain(db, workspace_id, settings.provider_id)
    result = await gateway.complete(
        providers,
        model=settings.model,
        messages=[
            {"role": "system", "content": settings.system_prompt},
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
    providers = await get_provider_chain(db, workspace_id, settings.provider_id)
    result = await gateway.complete(
        providers,
        model=settings.model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": input_text},
        ],
        temperature=settings.temperature,
    )
    return result, retrieved, prompt


async def _run_agent(
    settings: BuiltinAgentSettings,
    input_text: str,
    workspace_id: UUID,
    db: AsyncSession,
    gateway: LLMGateway,
) -> tuple[ChatResult, list[dict[str, object]], str]:
    providers = await get_provider_chain(db, workspace_id, settings.provider_id)
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
        {"role": "user", "content": input_text},
    ]
    calls: list[dict[str, object]] = []
    result: ChatResult | None = None
    tool_map = {tool.name: tool for tool in settings.tools}
    for _ in range(settings.max_steps):
        result = await gateway.complete(
            providers,
            model=settings.model,
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
            validate_json_schema(arguments, tool.parameters)
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
    try:
        row = json.loads(input_text)
    except json.JSONDecodeError as exc:
        raise ValueError("Upload-output test input must be a JSON object") from exc
    if not isinstance(row, dict):
        raise ValueError("Upload-output test input must be a JSON object")
    output = _mapped_value(row, settings.output_field)
    contexts = (
        _mapped_value(row, settings.retrieved_contexts_field)
        if settings.retrieved_contexts_field
        else None
    )
    return _trace_response(
        output,
        started,
        row,
        extras={
            "steps": ({"retrieved_chunks": contexts} if contexts is not None else {})
        },
    )


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
