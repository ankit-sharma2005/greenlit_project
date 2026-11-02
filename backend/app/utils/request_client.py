"""Shared SSRF-safe request client and helper functions for M3."""

from __future__ import annotations

import ipaddress
import os
import random
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

# A busy or briefly unavailable target is worth asking again. These are the
# answers that mean "not now", never a wrong question.
RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})
RETRY_AFTER_CAP_SECONDS = 60.0
RETRY_BASE_SECONDS = 0.25
RETRY_DELAY_CAP_SECONDS = 10.0

# Redirects are followed only while they stay on the host the user typed, and
# only a few times: a target must not be able to bounce the request to a host
# the SSRF guard never checked.
MAX_SAME_HOST_REDIRECTS = 3
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

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


class RedirectBlockedError(Exception):
    """A redirect pointed at another host and was not followed."""

    def __init__(self, target_host: str) -> None:
        super().__init__(target_host)
        self.target_host = target_host


class TooManyRedirectsError(Exception):
    """The target kept redirecting past the same-host limit."""

    def __init__(self, hops: int) -> None:
        super().__init__(hops)
        self.hops = hops


class RequestInterruptedError(Exception):
    """The caller asked to stop while this request was waiting to retry."""


class RequestDeadlineExceededError(Exception):
    """The item's total time budget ran out before another attempt could start."""


def _remaining_timeout(timeout: float, deadline: float | None) -> float:
    """How long one attempt may take: its own timeout, capped by the budget."""
    if deadline is None:
        return timeout
    left = deadline - time.monotonic()
    if left <= 0:
        raise RequestDeadlineExceededError("the item's time budget ran out")
    return min(timeout, left)


def _wait_for_retry(
    seconds: float,
    interrupt: threading.Event | None,
    deadline: float | None,
) -> float:
    """Sleep before a retry; returns the seconds actually waited.

    ``interrupt`` makes the wait stoppable (Cancel must not sit through a
    target's 30-second Retry-After), and ``deadline`` caps it so a slow target
    cannot outlive the item's budget.
    """
    if deadline is not None:
        seconds = max(0.0, min(seconds, deadline - time.monotonic()))
    started = time.monotonic()
    if interrupt is not None:
        if interrupt.wait(seconds):
            raise RequestInterruptedError("cancelled while waiting to retry")
    else:
        time.sleep(seconds)
    return time.monotonic() - started


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
        # What the last call did, so a caller can record a final-attempt latency
        # and the retries separately (a retried case is still a success).
        self.last_attempt_seconds = 0.0
        self.last_retry_count = 0
        self.last_waited_seconds = 0.0
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

    def _redirect_target(self, response: httpx.Response, current_url: str) -> str | None:
        """Where this response wants the request to go, if anywhere."""
        if response.status_code not in REDIRECT_STATUSES:
            return None
        location = response.headers.get("location")
        if not location:
            return None
        return str(urljoin(current_url, location))

    @staticmethod
    def _same_host(original: str, candidate: str) -> bool:
        """Same hostname as the URL the user typed (scheme and port may differ)."""
        left = (urlparse(original).hostname or "").lower()
        right = (urlparse(candidate).hostname or "").lower()
        return left == right

    def _request_following(
        self,
        client: httpx.Client,
        method: str,
        safe_url: str,
        headers: dict[str, str] | None,
        timeout: float,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send the request, following only same-host redirects.

        A redirect to another host is refused instead of followed: the SSRF
        guard checked the URL the user gave, not the one the target chose.
        """
        url = safe_url
        for hop in range(MAX_SAME_HOST_REDIRECTS + 1):
            response = client.request(method, url, headers=headers, timeout=timeout, **kwargs)
            target = self._redirect_target(response, url)
            if target is None:
                return response
            if not self._same_host(safe_url, target):
                raise RedirectBlockedError((urlparse(target).hostname or "").lower())
            if hop == MAX_SAME_HOST_REDIRECTS:
                raise TooManyRedirectsError(hop + 1)
            response.close()
            url = target
        raise TooManyRedirectsError(MAX_SAME_HOST_REDIRECTS + 1)

    def request(
        self,
        method: str = "POST",
        url: str = "",
        max_retries: int | None = None,
        *,
        interrupt: threading.Event | None = None,
        deadline: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        safe_url = self._sanitize_url(url)
        timeout = kwargs.pop("timeout", 60)
        safe_url, headers = self.local_target(safe_url, kwargs.pop("headers", None))
        retries = self.max_retries if max_retries is None else max(0, max_retries)
        attempts = retries + 1
        self.last_retry_count = 0
        self.last_waited_seconds = 0.0
        self.last_attempt_seconds = 0.0
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response: httpx.Response | None = None
            for attempt in range(attempts):
                attempt_timeout = _remaining_timeout(timeout, deadline)
                started = time.monotonic()
                response = self._request_following(
                    client, method, safe_url, headers, attempt_timeout, **kwargs
                )
                self.last_attempt_seconds = time.monotonic() - started
                self.last_retry_count = attempt
                if response.status_code not in RETRYABLE_STATUSES or attempt == attempts - 1:
                    return response
                self.last_waited_seconds += _wait_for_retry(
                    retry_delay(response, attempt), interrupt, deadline
                )
        # Unreachable: the loop always returns on its last attempt.
        assert response is not None
        return response

    @contextmanager
    def stream(
        self,
        method: str = "POST",
        url: str = "",
        max_retries: int | None = None,
        *,
        interrupt: threading.Event | None = None,
        deadline: float | None = None,
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
        self.last_retry_count = 0
        self.last_waited_seconds = 0.0
        self.last_attempt_seconds = 0.0
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            for attempt in range(attempts):
                delay: float | None = None
                attempt_timeout = _remaining_timeout(timeout, deadline)
                started = time.monotonic()
                url = safe_url
                hops = 0
                while True:
                    with client.stream(
                        method, url, headers=headers, timeout=attempt_timeout, **kwargs
                    ) as response:
                        target = self._redirect_target(response, url)
                        if target is not None:
                            # Same-host only, and only a few hops: read the empty
                            # body, then ask the next URL for the real answer.
                            response.read()
                            if not self._same_host(safe_url, target):
                                raise RedirectBlockedError(
                                    (urlparse(target).hostname or "").lower()
                                )
                            if hops >= MAX_SAME_HOST_REDIRECTS:
                                raise TooManyRedirectsError(hops + 1)
                            hops += 1
                            url = target
                            continue
                        if (
                            response.status_code not in RETRYABLE_STATUSES
                            or attempt == attempts - 1
                        ):
                            self.last_retry_count = attempt
                            self.last_attempt_seconds = time.monotonic() - started
                            yield response
                            return
                        # Drain the small "not now" body so the connection can be
                        # reused, then wait the target's own Retry-After or backoff.
                        response.read()
                        honoured = retry_after_seconds(response.headers.get("Retry-After"))
                        delay = honoured if honoured is not None else retry_delay(None, attempt)
                        self.last_attempt_seconds = time.monotonic() - started
                        self.last_retry_count = attempt
                    break
                if delay is not None:
                    self.last_waited_seconds += _wait_for_retry(delay, interrupt, deadline)


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
