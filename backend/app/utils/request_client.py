"""Shared SSRF-safe request client and helper functions for M3."""

from __future__ import annotations

import ipaddress
import os
import random
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

# A busy or briefly unavailable target is worth asking again. These are the
# answers that mean "not now", never a wrong question.
RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})
RETRY_AFTER_CAP_SECONDS = 60.0
RETRY_BASE_SECONDS = 0.25
RETRY_DELAY_CAP_SECONDS = 10.0

# Inside a dev container ``127.0.0.1`` is the container itself, so a target the user
# runs on their own computer is reached through the Docker gateway instead. The name
# can validate the request against it, so it must keep seeing the Host the user typed.
LOCAL_GATEWAY_HOST = "host.docker.internal"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _in_container() -> bool:
    return os.path.exists("/.dockerenv")


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


class SSLError(ValueError):
    pass


class DisallowedHostError(SSLError):
    pass


# Keep old names for compatibility
DisallowedHost = DisallowedHostError


class BlockedPrivateURLError(SSLError):
    pass


BlockedPrivateURL = BlockedPrivateURLError


class RequestClient:
    """SSRF-safe HTTP client for user-supplied URLs."""

    def __init__(
        self,
        allow_private_targets: bool = False,
        max_redirects: int = 5,
        local_rewrite: bool | None = None,
        max_retries: int = 3,
    ):
        self.allow_private_targets = allow_private_targets
        self.max_redirects = max_redirects
        self.max_retries = max(0, max_retries)
        # ``None`` means "ask the environment": only a container has to go through
        # the gateway, a process on the host reaches the app directly as before.
        self.local_rewrite = _in_container() if local_rewrite is None else local_rewrite

    def _is_private_host(self, hostname: str) -> bool:
        if hostname in ("localhost", "local", "home", "internal"):
            return True
        try:
            ip = ipaddress.ip_address(hostname)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
            ):
                return True
        except ValueError:
            pass
        for pattern in _PRIVATE_RANGES:
            if ":" not in hostname and hostname.startswith(pattern):
                return True
        return bool(hostname.startswith("169.254.") or hostname == "metadata.google.internal")

    def _sanitize_url(self, url: str) -> str:
        parsed = urlparse(url)
        if not parsed.hostname:
            raise DisallowedHost("URL must include a hostname")
        if self._is_private_host(parsed.hostname) and not self.allow_private_targets:
            raise BlockedPrivateURL(f"blocked private URL: {parsed.hostname}")
        if not parsed.scheme:
            url = "https://" + url
            parsed = urlparse(url)
        valid_schemes = {"http", "https"}
        if parsed.scheme not in valid_schemes:
            raise DisallowedHost(f"Unsupported scheme: {parsed.scheme}")
        return url

    def local_target(
        self, url: str, headers: dict[str, str] | None
    ) -> tuple[str, dict[str, str] | None]:
        """Connect through the gateway but keep the Host the user typed.

        Only loopback targets changed by the local-computer mode are touched; an
        arbitrary Host never comes from the caller, it is derived from the URL the
        user supplied after the same sanitising as an ordinary request.
        """
        if not (self.allow_private_targets and self.local_rewrite):
            return url, headers
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
            return url, headers
        host = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        rewritten = dict(headers or {})
        rewritten.pop("host", None)
        rewritten["Host"] = f"{host}{port}"
        connect_url = parsed._replace(netloc=f"{LOCAL_GATEWAY_HOST}{port}").geturl()
        return connect_url, rewritten

    def request(
        self,
        method: str = "POST",
        url: str = "",
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        safe_url = self._sanitize_url(url)
        timeout = kwargs.pop("timeout", 60)
        safe_url, headers = self.local_target(safe_url, kwargs.pop("headers", None))
        retries = self.max_retries if max_retries is None else max(0, max_retries)
        attempts = retries + 1
        with httpx.Client(
            timeout=timeout, follow_redirects=True, max_redirects=self.max_redirects
        ) as client:
            response: httpx.Response | None = None
            for attempt in range(attempts):
                response = client.request(method, safe_url, headers=headers, **kwargs)
                if response.status_code not in RETRYABLE_STATUSES or attempt == attempts - 1:
                    return response
                time.sleep(retry_delay(response, attempt))
        # Unreachable: the loop always returns on its last attempt.
        assert response is not None
        return response

    @contextmanager
    def stream(
        self,
        method: str = "POST",
        url: str = "",
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Iterator[httpx.Response]:
        """Open a streamed response with the same SSRF and retry rules.

        The caller reads the body inside the ``with`` block; a busy answer
        (429/502/503/504) is retried before anything is yielded, so a caller
        never sees half a retried stream.
        """
        safe_url = self._sanitize_url(url)
        timeout = kwargs.pop("timeout", 60)
        safe_url, headers = self.local_target(safe_url, kwargs.pop("headers", None))
        retries = self.max_retries if max_retries is None else max(0, max_retries)
        attempts = retries + 1
        with httpx.Client(
            timeout=timeout, follow_redirects=True, max_redirects=self.max_redirects
        ) as client:
            for attempt in range(attempts):
                delay: float | None = None
                with client.stream(method, safe_url, headers=headers, **kwargs) as response:
                    if response.status_code not in RETRYABLE_STATUSES or attempt == attempts - 1:
                        yield response
                        return
                    # Drain the small "not now" body so the connection can be
                    # reused, then wait the target's own Retry-After or backoff.
                    response.read()
                    honoured = retry_after_seconds(response.headers.get("Retry-After"))
                    delay = honoured if honoured is not None else retry_delay(None, attempt)
                if delay is not None:
                    time.sleep(delay)


def retry_after_seconds(value: str | None) -> float | None:
    """``Retry-After`` as seconds, from either a number or an HTTP date."""
    if not value:
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(UTC)).total_seconds()
    return max(0.0, min(seconds, RETRY_AFTER_CAP_SECONDS))


def retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Wait before retrying: the target's Retry-After, else exp backoff + jitter."""
    header = response.headers.get("Retry-After") if response is not None else None
    honoured = retry_after_seconds(header)
    if honoured is not None:
        return honoured
    backoff = RETRY_BASE_SECONDS * (2**attempt)
    return float(min(RETRY_DELAY_CAP_SECONDS, backoff + random.uniform(0, backoff / 2)))


def _is_private_host(hostname: str) -> bool:
    client = RequestClient(allow_private_targets=False)
    return client._is_private_host(hostname)


def _sanitize_url(url: str) -> str:
    client = RequestClient(allow_private_targets=False)
    return client._sanitize_url(url)


def _quote_input(text: str) -> str:
    text = text.replace("{{", "{{{[{[[")
    text = text.replace("}}", "]}}]}")
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
