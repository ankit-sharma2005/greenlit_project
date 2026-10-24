"""Provider services: connection testing, rate limiting, per-provider configs."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.models import Provider
from app.security.keys import decrypt_key


def _build_http_endpoint_url(base_url: str, path: str = "/v1/models") -> str:
    """Build the full URL for an HTTP endpoint test."""
    return base_url.rstrip("/") + path


def _build_prompt_app_payload(
    base_url: str,
    system_prompt: str,
    model: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Build the payload for a prompt-app connector test."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}],
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return payload


def _build_upload_outputs_payload(
    data: dict[str, Any] | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Build the payload for upload-outputs connector test."""
    payload: dict[str, Any] = {}
    if data:
        payload["data"] = data
    if filename:
        payload["filename"] = filename
    return payload


def _detect_answer_path(data: dict[str, Any], kind: str) -> str | None:
    """Auto-detect the answer path from an LLM response.

    Tries common answer keys in order, supporting dotted paths with list indexes.
    Returns the detected answer string or None if not found.
    """
    answer_keys = [
        "answer",
        "response",
        "output",
        "text",
        "message",
        "content",
        "result",
    ]
    openai_keys = [
        ("choices", [0], "message", "content"),
    ]

    # Try simple keys
    for key in answer_keys:
        if key in data:
            val = data[key]
            if isinstance(val, str):
                return val
            if isinstance(val, dict):
                return val.get("text") or val.get("content")

    # Try OpenAI shape: choices.0.message.content
    for prefix, *nested, final_key in openai_keys:
        current = data.get(prefix)
        if isinstance(current, list) and len(current) > 0:
            first = current[0]
            if isinstance(first, dict):
                # Navigate nested keys
                target: Any = first
                for nested_key in nested:
                    if isinstance(target, dict):
                        target = target.get(nested_key)
                if isinstance(target, dict):
                    return target.get(final_key)

    return None


def _detect_context_path(data: dict[str, Any]) -> list[Any] | None:
    """Auto-detect the context/retrieved_context path from an LLM response.

    Tries common context keys.
    Returns the detected context or None if not found.
    """
    context_keys = [
        "context",
        "contexts",
        "sources",
        "retrieved_context",
        "documents",
        "chunks",
    ]

    for key in context_keys:
        if key in data:
            val = data[key]
            if isinstance(val, list):
                return val
            if isinstance(val, str):
                return [val]
            if isinstance(val, dict):
                # Try common sub-keys
                for sub in ["texts", "chunks", "content", "documents"]:
                    sub_val = val.get(sub)
                    if isinstance(sub_val, list):
                        return sub_val
    return None


def _build_body_template(kind: str, input_placeholder: bool = True) -> str:
    """Build the request body template based on connector kind.

    Templates use {{input}} placeholder which gets JSON-encoded.
    """
    if kind == "openai-compatible":
        # OpenAI chat shape with {{input}}
        return '{"messages": [{"role": "user", "content": {{input}}}]}'
    elif kind == "groq":
        # Groq shape
        return '{"input": {{input}}}'
    else:
        # Default: try question first, then input
        if input_placeholder:
            return '{"question": {{input}}}'
        return '{"input": {{input}}}'


def _parse_body_template(template: str, input_text: str) -> str:
    """Parse a body template by replacing {{input}} with JSON-encoded input.

    The {{input}} is replaced by the JSON-encoded string of the question
    (quotes included), so the template {"question": {{input}}} becomes
    {"question": "hello world"} after parsing.
    """
    import json

    # Escape {{ and }} first to avoid double-replacement
    result = template.replace("{{{", "{{{[{[[")
    result = result.replace("}}}", "]]}]}")

    # Replace {{input}} with JSON-encoded input
    input_json = json.dumps(input_text)
    result = result.replace("{{input}}", input_json)

    # Unescape the placeholders we added
    result = result.replace("{{{[{[[", "{{{")
    result = result.replace("]]}]}", "}}")

    return result


def _is_private_host(hostname: str) -> bool:
    if hostname in ("localhost", "local", "home", "internal"):
        return True
    try:
        import ipaddress

        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return True
    except ValueError:
        pass
    private_ip_patterns = [
        "0.",
        "10.",
        "127.",
        "169.254.",
        "172.16.",
        "172.31.",
        "192.0.2.",
        "192.168.",
        "198.18.",
        "198.51.",
        "203.0.113.",
    ]
    for pattern in private_ip_patterns:
        if ":" not in hostname and hostname.startswith(pattern):
            return True
    return False


def _sanitize_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    if _is_private_host(parsed.hostname):
        raise ValueError(f"Refusing to connect to private/internal host: {parsed.hostname}")
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    valid_schemes = {"http", "https"}
    if parsed.scheme not in valid_schemes:
        raise ValueError(f"Unsupported scheme: {parsed.scheme}")
    return url


def _quote_input(text: str) -> str:
    text = text.replace("{{", "{{{[{[[")
    text = text.replace("}}", "]]}]}")
    text = text.replace("$", "\\$")
    text = text.replace("`", "\\`")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    return text


class RequestResult:
    def __init__(
        self,
        success: bool,
        status_code: int | None = None,
        data: dict[str, Any] | None = None,
        error: str | None = None,
        message: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        self.success = success
        self.status_code = status_code
        self.data = data or {}
        self.error = error
        self.message = message or ""
        self.latency_ms = latency_ms

    def __bool__(self) -> bool:
        return self.success


def make_request(
    url: str,
    timeout: float = 30,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    **kwargs: Any,
) -> RequestResult:
    try:
        safe_url = _sanitize_url(url)
    except ValueError as e:
        return RequestResult(success=False, error=str(e), message=str(e), latency_ms=0)
    import httpx

    last_error: httpx.HTTPError | None = None
    for attempt in range(max_retries):
        attempt_delay = backoff_factor**attempt
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(safe_url, follow_redirects=True, **kwargs)
                latency_ms = int(response.elapsed.total_seconds() * 1000)
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except Exception:
                        data = {"raw_response": response.text[:500]}
                    return RequestResult(
                        success=True,
                        status_code=response.status_code,
                        data=data,
                        message="Request successful",
                        latency_ms=latency_ms,
                    )
                elif response.status_code == 403:
                    return RequestResult(
                        success=False,
                        status_code=response.status_code,
                        error="Forbidden: Access denied to target",
                        message=f"HTTP 403: {response.text[:200]}",
                        latency_ms=latency_ms,
                    )
                elif response.status_code == 404:
                    return RequestResult(
                        success=False,
                        status_code=response.status_code,
                        error="Not found: Target endpoint does not exist",
                        message=f"HTTP 404: {response.text[:200]}",
                        latency_ms=latency_ms,
                    )
                else:
                    return RequestResult(
                        success=False,
                        status_code=response.status_code,
                        error=f"HTTP error: {response.status_code}",
                        message=f"HTTP {response.status_code}: {response.text[:200]}",
                        latency_ms=latency_ms,
                    )
        except httpx.TimeoutException as e:
            latency_ms = int((time.time() - getattr(e, "_start_ms", 0)) * 1000)
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(min(attempt_delay, 10))
            continue
        except httpx.ConnectError as e:
            latency_ms = int((time.time() - getattr(e, "_start_ms", 0)) * 1000)
            last_error = e
            return RequestResult(
                success=False,
                error=f"Connection error: {str(e)[:200]}",
                message=f"Connection error: {str(e)[:200]}",
                latency_ms=latency_ms,
            )
        except httpx.HTTPError as e:
            latency_ms = int((time.time() - getattr(e, "_start_ms", 0)) * 1000)
            last_error = e
            return RequestResult(
                success=False,
                error=f"HTTP error: {str(e)[:200]}",
                message=f"HTTP error: {str(e)[:200]}",
                latency_ms=latency_ms,
            )
    if last_error:
        latency_ms = int((time.time() - getattr(last_error, "_start_ms", 0)) * 1000)
        return RequestResult(
            success=False,
            error=f"Request failed after {max_retries} retries",
            message=f"Request failed after {max_retries} retries: {str(last_error)[:200]}",
            latency_ms=latency_ms,
        )
    return RequestResult(
        success=False,
        error="Request failed with no error details",
        message="Request failed with no error details",
        latency_ms=0,
    )


def test_provider_connection(provider: Provider) -> dict[str, Any]:
    """Test a provider's connection and return health status dict.

    Supports multiple connector types:
    - http_endpoint: Generic HTTP endpoint test
    - prompt_app: System prompt + model testing
    - upload_outputs: Upload CSV/JSON outputs testing
    """
    settings = get_settings()
    timeout = settings.provider_timeout_seconds or 30

    start_ms = time.time() * 1000
    kind = provider.kind or "openai-compatible"
    connector = provider.connector or "http_endpoint"
    base_url = provider.base_url or ""

    try:
        with httpx.Client(timeout=timeout) as client:
            if connector == "http_endpoint":
                return _test_http_endpoint(client, base_url, kind, timeout, start_ms, provider)
            elif connector == "prompt_app":
                return _test_prompt_app(client, base_url, kind, timeout, start_ms, provider)
            elif connector == "upload_outputs":
                return _test_upload_outputs(client, base_url, kind, timeout, start_ms, provider)
            else:
                # Default to http_endpoint behavior
                return _test_http_endpoint(client, base_url, kind, timeout, start_ms, provider)
    except httpx.TimeoutException:
        latency_ms = int((time.time() - start_ms) * 1000)
        return {
            "success": False,
            "message": f"Request timed out after {timeout}s",
            "latency_ms": latency_ms,
            "model": None,
            "is_free_tier": None,
            "privacy_warning": None,
            "connector": connector,
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
            "connector": connector,
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
            "connector": connector,
        }


def _test_http_endpoint(
    client: httpx.Client,
    base_url: str,
    kind: str,
    timeout: float,
    start_ms: float,
    provider: Provider,
) -> dict[str, Any]:
    """Test a generic HTTP endpoint."""
    endpoint = "/v1/models" if kind != "ollama" else "/api/tags"
    url = _build_http_endpoint_url(base_url, endpoint)
    headers = {}
    api_key_value = decrypt_key(provider.api_key_encrypted) if provider.api_key_encrypted else None
    if api_key_value:
        headers["Authorization"] = f"Bearer {api_key_value}"

    try:
        response = client.get(url, headers=headers, follow_redirects=True)
        latency_ms = int((time.time() - start_ms) * 1000)

        if response.status_code == 200:
            data = response.json()
            # Auto-detect answer path and context path
            detected_answer = _detect_answer_path(data, kind)
            detected_context = _detect_context_path(data)

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
                    "connector": "http_endpoint",
                    "detected_answer": detected_answer,
                    "detected_context": detected_context,
                }
            else:
                model = data.get("data", [{}])[0].get("id", None)
                free_tier = provider.is_active and not provider.is_premium
                privacy_warning = None
                if free_tier and provider.kind in {"groq", "openai-compatible"}:
                    privacy_warning = "Free tier: data may be used for model improvement"
                return {
                    "success": True,
                    "message": "Connection successful",
                    "latency_ms": latency_ms,
                    "model": model,
                    "is_free_tier": free_tier,
                    "privacy_warning": privacy_warning,
                    "connector": "http_endpoint",
                    "detected_answer": detected_answer,
                    "detected_context": detected_context,
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
                "connector": "http_endpoint",
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
            "connector": "http_endpoint",
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
            "connector": "http_endpoint",
        }


def _test_prompt_app(
    client: httpx.Client,
    base_url: str,
    kind: str,
    timeout: float,
    start_ms: float,
    provider: Provider,
) -> dict[str, Any]:
    """Test a prompt-app connector with system prompt + model."""
    # The prompt-app test posts to a /v1/chat/completions endpoint
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {}
    api_key_value = decrypt_key(provider.api_key_encrypted) if provider.api_key_encrypted else None
    if api_key_value:
        headers["Authorization"] = f"Bearer {api_key_value}"

    # Build payload with system prompt
    config = provider.provider_config or {}
    system_prompt = config.get("system_prompt", "")
    model = config.get("model", kind)
    temperature = float(config.get("temperature", 0.7))
    max_tokens = int(config.get("max_tokens", 100))

    payload = _build_prompt_app_payload(
        base_url=base_url,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    try:
        response = client.post(url, headers=headers, json=payload, follow_redirects=True)
        latency_ms = int((time.time() - start_ms) * 1000)

        if response.status_code == 200:
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                model_name = data.get("model", model)
                return {
                    "success": True,
                    "message": "Prompt app test successful",
                    "latency_ms": latency_ms,
                    "model": model_name,
                    "is_free_tier": provider.is_active and not provider.is_premium,
                    "privacy_warning": None,
                    "connector": "prompt_app",
                    "fields": {
                        "system_prompt": system_prompt,
                        "model": model,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        "response_content": content[:200] if content else "",
                    },
                }
            else:
                return {
                    "success": False,
                    "message": "No choices returned from prompt app",
                    "latency_ms": latency_ms,
                    "model": model,
                    "is_free_tier": provider.is_active and not provider.is_premium,
                    "privacy_warning": None,
                    "connector": "prompt_app",
                }
        else:
            truncated_msg = f"HTTP {response.status_code}: {response.text[:200]}"
            return {
                "success": False,
                "message": truncated_msg,
                "latency_ms": latency_ms,
                "model": model,
                "is_free_tier": provider.is_active and not provider.is_premium,
                "privacy_warning": None,
                "connector": "prompt_app",
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
            "connector": "prompt_app",
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
            "connector": "prompt_app",
        }


def _test_upload_outputs(
    client: httpx.Client,
    base_url: str,
    kind: str,
    timeout: float,
    start_ms: float,
    provider: Provider,
) -> dict[str, Any]:
    """Test upload-outputs connector."""
    url = base_url.rstrip("/") + "/v1/uploads/test"
    headers = {}
    api_key_value = decrypt_key(provider.api_key_encrypted) if provider.api_key_encrypted else None
    if api_key_value:
        headers["Authorization"] = f"Bearer {api_key_value}"

    # Build upload payload
    upload_data: dict[str, Any] = provider.provider_config or {}
    filename = upload_data.get("filename", "test-data.json")

    try:
        # POST with JSON payload representing the upload config
        response = client.post(
            url,
            headers=headers,
            json={"data": upload_data, "filename": filename},
            follow_redirects=True,
        )
        latency_ms = int((time.time() - start_ms) * 1000)

        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "message": "Upload output test successful",
                "latency_ms": latency_ms,
                "model": None,
                "is_free_tier": provider.is_active and not provider.is_premium,
                "privacy_warning": None,
                "connector": "upload_outputs",
                "fields": {
                    "filename": filename,
                    "upload_size": len(json.dumps(upload_data)),
                    "upload_response": data,
                },
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
                "connector": "upload_outputs",
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
            "connector": "upload_outputs",
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
            "connector": "upload_outputs",
        }
