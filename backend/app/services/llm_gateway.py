from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from openai.types.chat import ChatCompletionMessageParam

from app.config import settings
from app.models import ProviderConfig
from app.services.rate_limit import ProviderRateLimiter
from app.services.secrets import decrypt_secret

logger = logging.getLogger(__name__)
_MAX_UPSTREAM_ERROR_BODY = 2_000


class ProviderRequestError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        upstream_status_code: int | None = None,
        upstream_body: str | None = None,
    ) -> None:
        self.retryable = retryable
        self.upstream_status_code = upstream_status_code
        self.upstream_body = upstream_body
        super().__init__(message)


async def _validate_provider_target(base_url: str) -> None:
    parsed = urlsplit(base_url)
    host = parsed.hostname
    if host is None or parsed.scheme not in {"http", "https"}:
        raise ProviderRequestError("Provider base URL must be an HTTP(S) URL")
    allowed_hosts = {
        allowed.strip().casefold()
        for allowed in settings.allowed_private_hosts.split(",")
        if allowed.strip()
    }
    if host.casefold() in allowed_hosts:
        return
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except ValueError:
            continue
        if not ip.is_global:
            raise ProviderRequestError(
                "Private provider hosts are blocked. Configure ALLOWED_PRIVATE_HOSTS "
                "for an explicitly trusted local development host."
            )


def _upstream_error_body(provider: ProviderConfig, exc: APIStatusError) -> str:
    error_body = exc.response.text[:_MAX_UPSTREAM_ERROR_BODY]
    api_key = (
        decrypt_secret(provider.api_key_encrypted)
        if provider.api_key_encrypted
        else None
    )
    if api_key:
        error_body = error_body.replace(api_key, "[REDACTED]")
    logger.warning(
        "Provider upstream request failed: HTTP %d; body=%r",
        exc.status_code,
        error_body,
        extra={
            "provider_id": str(provider.id),
            "provider_type": provider.provider_type,
            "upstream_status_code": exc.status_code,
            "upstream_body": error_body,
        },
    )
    return error_body


def normalize_provider_base_url(provider_type: str, base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if provider_type != "ollama":
        return normalized

    parsed = urlsplit(normalized)
    path = parsed.path.rstrip("/")
    while path.endswith("/v1"):
        path = path[:-3].rstrip("/")
    path = f"{path}/v1"
    return urlunsplit(
        (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
    )


@dataclass(frozen=True)
class ChatResult:
    output: str
    model: str
    tokens_in: int | None
    tokens_out: int | None
    raw_response: dict[str, object]
    provider_id: UUID
    queue_position: int


class LLMGateway:
    def __init__(
        self,
        *,
        rate_limiter: ProviderRateLimiter | None = None,
        client_factory: Callable[..., httpx.AsyncClient] | None = None,
    ) -> None:
        self.rate_limiter = rate_limiter or ProviderRateLimiter()
        self.client_factory = client_factory or httpx.AsyncClient

    def _client(self, provider: ProviderConfig) -> AsyncOpenAI:
        api_key = (
            decrypt_secret(provider.api_key_encrypted)
            if provider.api_key_encrypted
            else "ollama"
        )
        http_client = self.client_factory(
            timeout=120.0 if provider.provider_type == "ollama" else 30.0,
            follow_redirects=False,
        )
        return AsyncOpenAI(
            api_key=api_key,
            base_url=normalize_provider_base_url(
                provider.provider_type, provider.base_url
            )
            + "/",
            http_client=http_client,
            max_retries=0,
        )

    async def test_connection(
        self, provider: ProviderConfig, *, model: str | None = None
    ) -> dict[str, object]:
        await _validate_provider_target(provider.base_url)
        await self.rate_limiter.wait_for_slot(provider.id, provider.rpm, provider.rpd)
        model = model or provider.test_model
        client = self._client(provider)
        try:
            if model:
                completion = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Reply with OK."}],
                    temperature=0,
                    max_tokens=16,
                )
                output = completion.choices[0].message.content
                return {
                    "models": [completion.model],
                    "test_model": model,
                    "output": output if isinstance(output, str) else "",
                }
            models = await client.models.list()
            return {"models": [item.id for item in models.data]}
        except APIConnectionError as exc:
            raise ProviderRequestError(
                "Could not connect to the configured provider", retryable=True
            ) from exc
        except APITimeoutError as exc:
            raise ProviderRequestError(
                "The provider connection timed out", retryable=True
            ) from exc
        except APIStatusError as exc:
            error_body = _upstream_error_body(provider, exc)
            raise ProviderRequestError(
                f"Provider returned HTTP {exc.status_code}: {error_body}",
                retryable=exc.status_code == 429 or exc.status_code >= 500,
                upstream_status_code=exc.status_code,
                upstream_body=error_body,
            ) from exc
        finally:
            await client.close()

    async def complete(
        self,
        providers: Sequence[ProviderConfig],
        *,
        model: str | None,
        messages: list[ChatCompletionMessageParam],
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> ChatResult:
        if not providers:
            raise ProviderRequestError("No configured provider is available")

        failures: list[str] = []
        for index, provider in enumerate(providers):
            effective_model = model or provider.test_model
            if not effective_model:
                raise ProviderRequestError(
                    f"Provider '{provider.name}' has no default model configured"
                )
            try:
                return await self._complete_with_provider(
                    provider,
                    model=effective_model,
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                )
            except ProviderRequestError as exc:
                if not exc.retryable or index == len(providers) - 1:
                    raise
                failures.append(f"{provider.name}: {exc}")
        raise ProviderRequestError(
            "All configured providers failed: " + "; ".join(failures)
        )

    async def _complete_with_provider(
        self,
        provider: ProviderConfig,
        *,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float,
        max_output_tokens: int | None,
    ) -> ChatResult:
        await _validate_provider_target(provider.base_url)
        approximate_input_tokens = sum(
            len(str(message.get("content", ""))) // 4 for message in messages
        )
        if approximate_input_tokens > provider.max_input_tokens:
            raise ProviderRequestError(
                "Input exceeds the provider's configured token limit"
            )

        queue_position = await self.rate_limiter.wait_for_slot(
            provider.id, provider.rpm, provider.rpd
        )
        client = self._client(provider)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=min(
                    max_output_tokens or provider.max_output_tokens,
                    provider.max_output_tokens,
                ),
            )
        except APIConnectionError as exc:
            raise ProviderRequestError(
                "Could not connect to the configured provider", retryable=True
            ) from exc
        except APITimeoutError as exc:
            raise ProviderRequestError(
                "The provider request timed out", retryable=True
            ) from exc
        except APIStatusError as exc:
            error_body = _upstream_error_body(provider, exc)
            raise ProviderRequestError(
                f"Provider returned HTTP {exc.status_code}: {error_body}",
                retryable=exc.status_code == 429 or exc.status_code >= 500,
                upstream_status_code=exc.status_code,
                upstream_body=error_body,
            ) from exc
        finally:
            await client.close()

        output = response.choices[0].message.content
        if not isinstance(output, str):
            raise ProviderRequestError("Provider returned no text output")
        usage = response.usage
        return ChatResult(
            output=output,
            model=response.model,
            tokens_in=usage.prompt_tokens if usage else None,
            tokens_out=usage.completion_tokens if usage else None,
            raw_response=response.model_dump(mode="json"),
            provider_id=provider.id,
            queue_position=queue_position,
        )
