"""Single gateway for every LLM call (spec section 6).

One place for timeouts, retries with exponential backoff, and per-provider
request rate limits. The per-provider ``tokens_per_minute`` value is stored
and displayed, but not enforced pre-call: a trustworthy limit would need a
model-specific tokenizer before the request exists.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from app.models import Provider
from app.security.keys import decrypt_key
from app.security.rate_limit import RateLimiter

DEFAULT_REQUESTS_PER_MINUTE = 30
DEFAULT_MAX_TOKENS = 2048
MAX_BACKOFF_SECONDS = 30.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GatewayError(Exception):
    """An LLM call failed; ``code`` maps to an HTTP status in the API layer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LLMGateway:
    """``chat(provider, messages, temperature, max_tokens)`` with limits applied."""

    def __init__(
        self,
        rate_limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        post: Callable[..., httpx.Response] | None = None,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._sleep = sleep
        self._post = post or httpx.post

    def chat(
        self,
        provider: Provider,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> str:
        """One chat completion against an OpenAI-compatible endpoint."""
        if not provider.base_url:
            raise GatewayError(
                "provider_unavailable",
                f"Provider '{provider.name}' has no base URL configured.",
            )
        if not self._within_rate_limit(provider):
            raise GatewayError(
                "rate_limited",
                f"Provider '{provider.name}' is limited to "
                f"{self._requests_per_minute(provider)} requests/minute. "
                "Wait a moment and retry.",
            )

        url = provider.base_url.rstrip("/") + "/chat/completions"
        headers: dict[str, str] = {}
        if provider.api_key_encrypted:
            api_key = decrypt_key(provider.api_key_encrypted)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        payload: dict[str, Any] = {
            "model": model or provider.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if params:
            payload.update(params)

        attempts = max(provider.max_retries, 0) + 1
        last_error: GatewayError | None = None
        for attempt in range(attempts):
            try:
                response = self._post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=float(provider.timeout_seconds),
                )
            except httpx.TimeoutException:
                last_error = GatewayError(
                    "provider_unavailable",
                    f"Provider '{provider.name}' timed out after {provider.timeout_seconds}s.",
                )
            except httpx.HTTPError as exc:
                last_error = GatewayError(
                    "provider_unavailable",
                    f"Could not reach provider '{provider.name}': {str(exc)[:200]}",
                )
            else:
                if response.status_code == 200:
                    return self._content(provider, response)
                last_error = GatewayError(
                    "provider_unavailable",
                    f"Provider '{provider.name}' answered HTTP {response.status_code}: "
                    f"{response.text[:200]}",
                )
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    raise last_error
            if attempt < attempts - 1:
                backoff = provider.backoff_factor * (2**attempt)
                self._sleep(min(backoff, MAX_BACKOFF_SECONDS))
        assert last_error is not None
        raise last_error

    def _requests_per_minute(self, provider: Provider) -> int:
        return provider.rate_limit_per_minute or DEFAULT_REQUESTS_PER_MINUTE

    def _within_rate_limit(self, provider: Provider) -> bool:
        if self._rate_limiter is None:
            return True
        return self._rate_limiter.allow(
            f"llm:{provider.id}",
            self._requests_per_minute(provider),
            60,
        )

    @staticmethod
    def _content(provider: Provider, response: httpx.Response) -> str:
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayError(
                "invalid_response",
                f"Provider '{provider.name}' returned an unexpected response shape.",
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise GatewayError(
                "invalid_response",
                f"Provider '{provider.name}' returned an empty response.",
            )
        return content
