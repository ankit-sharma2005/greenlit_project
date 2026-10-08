from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from openai.types.chat import ChatCompletionMessageParam

from app.models import ProviderConfig
from app.services.rate_limit import ProviderRateLimiter
from app.services.secrets import decrypt_secret


class ProviderRequestError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        self.retryable = retryable
        super().__init__(message)


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
            timeout=20.0,
            follow_redirects=False,
        )
        return AsyncOpenAI(
            api_key=api_key,
            base_url=provider.base_url.rstrip("/") + "/",
            http_client=http_client,
            max_retries=0,
        )

    async def test_connection(self, provider: ProviderConfig) -> list[str]:
        await self.rate_limiter.wait_for_slot(provider.id, provider.rpm, provider.rpd)
        client = self._client(provider)
        try:
            response = await client.models.list()
            return [model.id for model in response.data]
        except APIConnectionError as exc:
            raise ProviderRequestError(
                "Could not connect to the configured provider", retryable=True
            ) from exc
        except APITimeoutError as exc:
            raise ProviderRequestError(
                "The provider connection timed out", retryable=True
            ) from exc
        except APIStatusError as exc:
            raise ProviderRequestError(
                f"Provider returned HTTP {exc.status_code}",
                retryable=exc.status_code == 429 or exc.status_code >= 500,
            ) from exc
        finally:
            await client.close()

    async def complete(
        self,
        providers: Sequence[ProviderConfig],
        *,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
    ) -> ChatResult:
        if not providers:
            raise ProviderRequestError("No configured provider is available")

        failures: list[str] = []
        for index, provider in enumerate(providers):
            try:
                return await self._complete_with_provider(
                    provider,
                    model=model,
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
            raise ProviderRequestError(
                f"Provider returned HTTP {exc.status_code}",
                retryable=exc.status_code == 429 or exc.status_code >= 500,
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
