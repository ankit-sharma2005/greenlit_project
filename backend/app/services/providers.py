"""Provider services: connection testing, rate limiting, per-provider configs."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import get_settings
from app.models import Provider
from app.security.keys import decrypt_key


def test_provider_connection(provider: Provider) -> dict[str, Any]:
    """Test a provider's connection and return health status dict."""
    settings = get_settings()
    timeout = settings.provider_timeout_seconds or 30

    start_ms = time.time() * 1000
    try:
        with httpx.Client(timeout=timeout) as client:
            base_url = provider.base_url or ""
            kind = provider.kind or "openai-compatible"
            endpoint = "/v1/models" if kind != "ollama" else "/api/tags"

            url = base_url.rstrip("/") + endpoint
            headers = {}
            api_key_value = (
                decrypt_key(provider.api_key_encrypted)
                if provider.api_key_encrypted
                else None
            )
            if api_key_value:
                headers["Authorization"] = f"Bearer {api_key_value}"

            response = client.get(url, headers=headers, follow_redirects=True)
            latency_ms = int((time.time() - start_ms) * 1000)

            if response.status_code == 200:
                data = response.json()
                kind = provider.kind or "openai-compatible"
                if kind == "ollama":
                    models = data.get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    model = next(
                        (m for m in models if "hermes" in model_names),
                        models[0] if models else None,
                    )
                    return {
                        "success": True,
                        "message": "Connection successful",
                        "latency_ms": latency_ms,
                        "model": model.model_name if model else None,
                        "is_free_tier": True,
                        "privacy_warning": None,
                    }
                else:
                    model = data.get("data", [{}])[0].get("id", None)
                    free_tier = provider.is_active and not provider.is_premium
                    privacy_warning = None
                    if free_tier and provider.kind in {
                        "groq",
                        "openai-compatible",
                    }:
                        privacy_warning = "Free tier: data may be used for model improvement"
                    return {
                        "success": True,
                        "message": "Connection successful",
                        "latency_ms": latency_ms,
                        "model": model,
                        "is_free_tier": free_tier,
                        "privacy_warning": privacy_warning,
                    }
            else:
                truncated_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                return {
                    "success": False,
                    "message": truncated_msg,
                    "latency_ms": latency_ms,
                    "model": None,
                    "is_free_tier": None,
                    "privacy_warning": None,
                }
    except httpx.TimeoutException:
        latency_ms = int((time.time() - start_ms) * 1000)
        return {
            "success": False,
            "message": f"Request timed out after {timeout}s",
            "latency_ms": latency_ms,
            "model": None,
            "is_free_tier": None,
            "privacy_warning": None,
        }
    except httpx.ConnectError as e:
        latency_ms = int((time.time() - start_ms) * 1000)
        return {
            "success": False,
            "message": f"Connection error: {str(e)[:200]}",
            "latency_ms": latency_ms,
            "model": None,
            "is_free_tier": None,
            "privacy_warning": None,
        }
    except Exception as e:
        latency_ms = int((time.time() - start_ms) * 1000)
        return {
            "success": False,
            "message": f"Error: {str(e)[:200]}",
            "latency_ms": latency_ms,
            "model": None,
            "is_free_tier": None,
            "privacy_warning": None,
        }
