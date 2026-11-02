"""One vocabulary for why a case failed.

The timeout rate used to be guessed from the error text, which is fragile: a
provider that says "request aborted" or a translated message slipped through as
an ordinary error. Connectors now label the failure with one of these kinds when
they raise, the worker stores the label on the case, and the metrics read the
label first. The text heuristic stays as a fallback for runs recorded before the
label existed.
"""

from __future__ import annotations

TIMEOUT = "timeout"
CONNECTION = "connection"
HTTP_ERROR = "http_error"
INVALID_RESPONSE = "invalid_response"
OTHER = "other"

ERROR_KINDS: tuple[str, ...] = (TIMEOUT, CONNECTION, HTTP_ERROR, INVALID_RESPONSE, OTHER)

# Existing error codes, mapped onto the vocabulary above. Codes stay as they are
# because the API maps them to statuses and the UI shows their messages.
_KIND_BY_CODE: dict[str, str] = {
    "timeout": TIMEOUT,
    "connect_timeout": TIMEOUT,
    "connection_error": CONNECTION,
    "connection_reset": CONNECTION,
    "tls_error": CONNECTION,
    "dns_error": CONNECTION,
    "provider_unavailable": CONNECTION,
    "http_error": HTTP_ERROR,
    "auth_error": HTTP_ERROR,
    "blocked_by_site": HTTP_ERROR,
    "redirect_blocked": OTHER,
    "redirect_loop": OTHER,
    "incomplete_stream": INVALID_RESPONSE,
    "not_found": HTTP_ERROR,
    "invalid_json": INVALID_RESPONSE,
    "invalid_response": INVALID_RESPONSE,
    "wrong_answer_path": INVALID_RESPONSE,
    "response_too_large": INVALID_RESPONSE,
    "template_error": OTHER,
    "connector_error": OTHER,
    "auto_detect_failed": OTHER,
    "empty_file": OTHER,
    "invalid_csv": OTHER,
    "unexpected_error": OTHER,
}


def kind_for_code(code: str | None) -> str:
    """The kind for an existing error code; ``other`` when nothing matches."""
    if not code:
        return OTHER
    return _KIND_BY_CODE.get(code, OTHER)
