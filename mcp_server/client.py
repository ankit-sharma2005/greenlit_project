"""Thin HTTP client for the GreenLit REST API.

The MCP server reaches GreenLit the same way a browser and ``scripts/greenlit_ci.py``
do: it signs in with an email and password, keeps the httpOnly session cookie in
memory and sends it back on every request. There is no API token type of its own,
no database access and no import of the application's internals.

Every failure leaves this module as a :class:`GreenLitError` that names what went
wrong, the HTTP status, and the host and path, with the credentials redacted.
"""

from __future__ import annotations

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

REDACTED = "XXXX"
JSON_LIMIT_BYTES = 1_000_000
TEXT_LIMIT_BYTES = 400_000
LOGIN_PATH = "/api/v1/auth/login"


class GreenLitError(Exception):
    """One API failure, reduced to what a person needs to read."""

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status: int | None,
        host: str,
        path: str,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.host = host
        self.path = path

    def __str__(self) -> str:
        state = f"HTTP {self.status}" if self.status is not None else "no response"
        return f"GreenLit {self.kind} ({state}) at {self.host}{self.path}: {self.message}"


def redact(text: str, *secrets: str) -> str:
    """Replace every occurrence of each secret with ``XXXX``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def _kind_for(status: int) -> str:
    if status == 401:
        return "authentication"
    if status == 403:
        return "permission"
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status == 422:
        return "invalid_request"
    if status == 429:
        return "rate_limited"
    if status == 408 or status == 504:
        return "timeout"
    if status >= 500:
        return "server_error"
    return "request_failed"


class GreenLitClient:
    """A signed-in session against one GreenLit API."""

    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        timeout: float = 30.0,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise GreenLitError(
                "configuration",
                "GREENLIT_URL must be a full http(s) URL such as http://localhost:8003.",
                status=None,
                host=base_url.strip(),
                path="",
            )
        self.base_url = base_url.strip().rstrip("/")
        self._host = parsed.netloc
        self._email = email
        self._password = password
        self._signed_in = False
        self.timeout = timeout
        self._cookies = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookies)
        )

    def redact(self, text: str) -> str:
        """Scrub the credentials out of any text this client produces."""
        return redact(text, self._password, self._email)

    def _error(
        self,
        kind: str,
        message: str,
        *,
        status: int | None,
        path: str,
    ) -> GreenLitError:
        return GreenLitError(
            kind,
            self.redact(message),
            status=status,
            host=self._host,
            path=path,
        )

    def _message_from(self, body: bytes) -> str:
        try:
            parsed: Any = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return ""
        if not isinstance(parsed, dict):
            return ""
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        detail = parsed.get("detail")
        if isinstance(detail, str):
            return detail
        return ""

    def _send(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        limit: int,
    ) -> bytes:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                body: bytes = response.read(limit)
                return body
        except urllib.error.HTTPError as exc:
            body = exc.read(limit)
            message = self._message_from(body) or "the API refused the request."
            raise self._error(_kind_for(exc.code), message, status=exc.code, path=path) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise self._error(
                "network",
                f"could not reach the API ({reason}).",
                status=None,
                path=path,
            ) from None

    def login(self) -> None:
        """Sign in and keep the session cookie. Never echoes a credential."""
        try:
            self._send(
                "POST",
                LOGIN_PATH,
                {"email": self._email, "password": self._password},
                JSON_LIMIT_BYTES,
            )
        except GreenLitError as exc:
            if exc.status == 401:
                raise self._error(
                    "authentication",
                    "the email or password was rejected.",
                    status=401,
                    path=LOGIN_PATH,
                ) from None
            raise
        self._signed_in = True

    def _send_with_session(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        limit: int,
    ) -> bytes:
        """Send one request, signing in first and once more after a 401."""
        if not self._signed_in:
            self.login()
        relogged_in = False
        while True:
            try:
                return self._send(method, path, payload, limit)
            except GreenLitError as exc:
                if exc.status == 401 and not relogged_in:
                    # The cookie expired: sign in again, once, and retry.
                    self.login()
                    relogged_in = True
                    continue
                if exc.status == 401:
                    raise self._error(
                        "authentication",
                        "the session was rejected even after signing in again.",
                        status=401,
                        path=path,
                    ) from None
                raise

    def _parse(self, body: bytes, path: str) -> dict[str, Any]:
        try:
            parsed: Any = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise self._error(
                "bad_response",
                "the API answered with something that is not JSON.",
                status=None,
                path=path,
            ) from None
        if not isinstance(parsed, dict):
            raise self._error(
                "bad_response",
                "the API answered with an unexpected body.",
                status=None,
                path=path,
            )
        return parsed

    def get_json(self, path: str) -> dict[str, Any]:
        body = self._send_with_session("GET", path, None, JSON_LIMIT_BYTES)
        return self._parse(body, path)

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = self._send_with_session("POST", path, payload, JSON_LIMIT_BYTES)
        return self._parse(body, path)

    def get_text(self, path: str) -> str:
        body = self._send_with_session("GET", path, None, TEXT_LIMIT_BYTES)
        return body.decode("utf-8", errors="replace")
