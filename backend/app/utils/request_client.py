"""Shared SSRF-safe request client and helper functions for M3."""

from __future__ import annotations

import ipaddress
import time
from typing import Any
from urllib.parse import urlparse

_PRIVATE_RANGES = [
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
    "::1",
    "fe80::",
    "ff00::",
]


def _is_private_host(hostname: str) -> bool:
    if hostname in ("localhost", "local", "home", "internal"):
        return True
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return True
        for pattern in _PRIVATE_RANGES:
            if ":" not in hostname and hostname.startswith(pattern):
                return True
    except ValueError:
        pass
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
