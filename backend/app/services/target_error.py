"""Structured, redacted detail for a failed target call.

A run used to record only "Response was not valid JSON" or a generic message,
which left nobody able to tell a wrong path from a 500. This module turns a
failure into the four facts a person needs:

* the structured kind (``timeout``, ``connection``, ``http_error`` ...);
* the HTTP status, when the target answered at all;
* the target as host + path only — never the query string, which is where
  tokens end up;
* a short snippet of the response body with secrets removed.

Everything here is pure and shared by the HTTP connector, the LLM gateway and
the dashboard, so the same failure reads the same way everywhere.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from app.services.error_kinds import CONNECTION, HTTP_ERROR, INVALID_RESPONSE, OTHER, TIMEOUT

SNIPPET_LIMIT = 300

# Anything that looks like a credential is replaced before the text is stored.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization: Bearer <token> / Basic <token>
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    # Whole credential headers, including a cookie jar echoed back.
    (re.compile(r"(?i)\b(cookie|set-cookie)\s*:\s*[^\r\n]+"), "Cookie: [redacted]"),
    # Headers and query/form style keys: api_key=..., session=...
    (
        re.compile(
            r"(?i)\b(api[-_]?key|access[-_]?token|refresh[-_]?token|session[-_]?id|session|"
            r"sid|token|secret|password|authorization)\b\s*[:=]\s*\"?([^\"\s,;&}]+)"
        ),
        r"\1=[redacted]",
    ),
    # Common provider key shapes.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[redacted]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "[redacted]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"), "[redacted]"),
)


def redact_snippet(text: str | None, limit: int = SNIPPET_LIMIT) -> str:
    """A bounded, credential-free excerpt of a response body."""
    if not text:
        return ""
    cleaned = str(text)
    for pattern, replacement in _SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    # Collapse whitespace so a multi-line HTML error page stays one line.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > limit:
        return cleaned[: max(limit - 1, 0)].rstrip() + "…"
    return cleaned


def target_of(url: str | None) -> str:
    """``host[:port]/path`` for a URL: no scheme, query string, fragment or userinfo."""
    if not url:
        return ""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return ""
    host = parts.hostname or ""
    if not host:
        return ""
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path or "/"
    return f"{host}{path}"


def describe(
    kind: str,
    message: str,
    *,
    status: int | None = None,
    target: str = "",
    snippet: str = "",
    timeout_seconds: int | float | None = None,
) -> str:
    """One specific line for this failure, in the words the UI and report use."""
    where = f" at {target}" if target else ""
    if kind == HTTP_ERROR and status is not None:
        line = f"Target returned HTTP {status}{where}"
    elif kind == CONNECTION:
        line = f"Target refused the connection{where}"
    elif kind == TIMEOUT:
        waited = f" after {timeout_seconds} s" if timeout_seconds else ""
        line = f"Timed out{waited}{where}"
    elif kind == INVALID_RESPONSE and snippet:
        line = f"Target answered{where} but the body could not be read"
    elif kind == OTHER and snippet:
        line = f"Request failed{where}"
    else:
        line = f"Request failed{where}"
    if message and message not in line:
        line = f"{line}: {message}"
    if snippet:
        line = f"{line} — {snippet}"
    return line


def error_detail(
    *,
    kind: str,
    message: str,
    status: int | None = None,
    target: str = "",
    snippet: str = "",
    timeout_seconds: int | float | None = None,
) -> dict[str, Any]:
    """The dict stored on the run item (and returned by the API)."""
    cleaned = redact_snippet(snippet)
    return {
        "kind": kind,
        "status": status,
        "target": target,
        "snippet": cleaned,
        "message": message,
        "summary": describe(
            kind,
            message,
            status=status,
            target=target,
            snippet=cleaned,
            timeout_seconds=timeout_seconds,
        ),
    }
