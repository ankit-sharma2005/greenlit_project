"""Unit tests for the LLM gateway: retries, backoff, rate limits, parsing."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.models import Provider
from app.security.keys import encrypt_key
from app.services.llm_gateway import GatewayError, LLMGateway

MESSAGES = [{"role": "user", "content": "q"}]


def _provider(**overrides: Any) -> Provider:
    values: dict[str, Any] = {
        "name": "gw-test",
        "kind": "openai-compatible",
        "model_name": "test-model",
        "base_url": "http://llm.test/v1",
        "timeout_seconds": 5,
        "max_retries": 2,
        "backoff_factor": 0.0,
    }
    values.update(overrides)
    return Provider(**values)


def _ok(content: str = "hi") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


class FakeLimiter:
    def __init__(self, allowed: int) -> None:
        self.allowed = allowed
        self.calls = 0

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        self.calls += 1
        return self.calls <= self.allowed

    def reset(self, key: str) -> None:
        return None


def test_chat_success_builds_openai_request() -> None:
    calls: list[dict[str, Any]] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return _ok()

    provider = _provider(api_key_encrypted=encrypt_key("sk-test"))
    gateway = LLMGateway(post=post, sleep=lambda _s: None)
    content = gateway.chat(provider, MESSAGES, 0.0, 128)

    assert content == "hi"
    assert calls[0]["url"] == "http://llm.test/v1/chat/completions"
    assert calls[0]["timeout"] == 5.0
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"
    payload = calls[0]["json"]
    assert payload["model"] == "test-model"
    assert payload["temperature"] == 0.0
    assert payload["max_tokens"] == 128


def test_chat_retries_retryable_status_then_succeeds() -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    def post(url: str, **kwargs: Any) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return _ok("recovered")

    provider = _provider(backoff_factor=1.5)
    gateway = LLMGateway(post=post, sleep=sleeps.append)

    assert gateway.chat(provider, MESSAGES) == "recovered"
    assert calls["n"] == 2
    assert sleeps == [1.5]  # backoff_factor * 2**0


def test_chat_does_not_retry_client_errors() -> None:
    calls = {"n": 0}

    def post(url: str, **kwargs: Any) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    gateway = LLMGateway(post=post, sleep=lambda _s: None)
    with pytest.raises(GatewayError) as excinfo:
        gateway.chat(_provider(), MESSAGES)

    assert calls["n"] == 1
    assert "401" in excinfo.value.message


def test_chat_timeout_retries_then_fails() -> None:
    calls = {"n": 0}

    def post(url: str, **kwargs: Any) -> httpx.Response:
        calls["n"] += 1
        raise httpx.TimeoutException("timeout")

    provider = _provider(max_retries=1)
    gateway = LLMGateway(post=post, sleep=lambda _s: None)
    with pytest.raises(GatewayError) as excinfo:
        gateway.chat(provider, MESSAGES)

    assert calls["n"] == 2  # max_retries + 1 attempts
    assert excinfo.value.code == "provider_unavailable"
    assert "timed out" in excinfo.value.message


def test_chat_rate_limited_before_any_call() -> None:
    calls = {"n": 0}

    def post(url: str, **kwargs: Any) -> httpx.Response:
        calls["n"] += 1
        return _ok()

    limiter = FakeLimiter(allowed=0)
    gateway = LLMGateway(rate_limiter=limiter, post=post)
    with pytest.raises(GatewayError) as excinfo:
        gateway.chat(_provider(), MESSAGES)

    assert excinfo.value.code == "rate_limited"
    assert calls["n"] == 0
    assert limiter.calls == 1


def test_chat_rate_limit_uses_provider_override() -> None:
    seen: list[int] = []

    class Capture:
        def allow(self, key: str, limit: int, window_seconds: int) -> bool:
            seen.append(limit)
            return True

        def reset(self, key: str) -> None:
            return None

    gateway = LLMGateway(rate_limiter=Capture(), post=lambda *_a, **_k: _ok())
    gateway.chat(_provider(rate_limit_per_minute=5), MESSAGES)
    assert seen == [5]


def test_chat_rejects_unexpected_shape() -> None:
    gateway = LLMGateway(post=lambda *_a, **_k: httpx.Response(200, json={"choices": []}))
    with pytest.raises(GatewayError) as excinfo:
        gateway.chat(_provider(max_retries=0), MESSAGES)
    assert excinfo.value.code == "invalid_response"


def test_chat_rejects_empty_content() -> None:
    gateway = LLMGateway(post=lambda *_a, **_k: _ok("  "))
    with pytest.raises(GatewayError) as excinfo:
        gateway.chat(_provider(max_retries=0), MESSAGES)
    assert excinfo.value.code == "invalid_response"


def test_chat_requires_base_url() -> None:
    gateway = LLMGateway(post=lambda *_a, **_k: _ok())
    with pytest.raises(GatewayError) as excinfo:
        gateway.chat(_provider(base_url=None), MESSAGES)
    assert excinfo.value.code == "provider_unavailable"
