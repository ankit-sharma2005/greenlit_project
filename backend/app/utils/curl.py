"""Parse curl commands into request parts (M3), including credentials.

A pasted curl command is how a person gives GreenLit a chatbot session that
needs a cookie or a bearer token. Header values never leave the server in a
response: the API returns the names and an encrypted blob that a later run can
send back. Headers the client must derive itself are never imported: ``Host`` (the URL
decides the host, so a pasted header cannot redirect the request or dodge the
SSRF check), the HTTP/2 pseudo-headers Chrome copies (``:authority``,
``:path`` ... — not legal header names in HTTP/1.1), ``Content-Length`` (the
rendered body is not the copied one, and a stale length makes the request
unreadable) and ``Accept-Encoding`` (the client may only negotiate encodings it
can decode).
"""

from __future__ import annotations

import base64
import json
import re
import shlex
from dataclasses import dataclass, field

from app.security.keys import decrypt_key, encrypt_key

_DATA_FLAGS = ("--data-raw", "--data-binary", "--data-ascii", "--data", "-d")


@dataclass
class ParsedCurl:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body_template: str | None = None
    header_count: int = 0


def _quote_pattern() -> str:
    return r"""(?:"([^"]*)"|'([^']*)'|(\S+))"""


def _unquote(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip()


# Headers a copied cURL carries that the client has to own. A pasted
# ``content-length`` describes the body Chrome sent, not the body GreenLit
# renders; a pasted ``accept-encoding`` can ask for an encoding the client
# cannot decode. Both turn a working paste into a 400 or an unreadable answer.
CLIENT_OWNED_HEADERS = frozenset({"host", "content-length", "accept-encoding"})
_CLIENT_OWNED_HEADERS = CLIENT_OWNED_HEADERS


def clean_request_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    """The headers a request may send: no client-owned names, no pseudo-headers.

    Applied when a cURL is imported *and* before a request is sent, so a target
    saved before this rule existed stops failing too.
    """
    if not headers:
        return headers
    cleaned: dict[str, str] = {}
    for name, value in headers.items():
        key = str(name).strip()
        lowered = key.lower()
        if not key or lowered in CLIENT_OWNED_HEADERS or key.startswith(":"):
            continue
        cleaned[key] = value
    return cleaned


def _add_header(headers: dict[str, str], raw: str) -> None:
    """Add one ``Name: value`` header, dropping the ones the client must set."""
    if ":" not in raw:
        return
    name, value = raw.split(":", 1)
    name = name.strip()
    if not name or name.lower() in CLIENT_OWNED_HEADERS:
        return
    # HTTP/2 pseudo-headers arrive as ":authority: host" from DevTools' copy;
    # they are request-line data, not headers, and no HTTP/1.1 client may send
    # them. Accepting one used to fail the whole request with
    # "Illegal header name b':authority'".
    if name.startswith(":"):
        return
    headers[name] = value.strip()


def parse_curl(curl: str) -> ParsedCurl | None:
    if not curl or not curl.strip().lower().startswith("curl"):
        return None

    text = curl.strip()

    try:
        tokens = shlex.split(text)
    except ValueError:
        return None
    url = ""
    skip_value = False
    value_options = {
        "-X",
        "--request",
        "-H",
        "--header",
        "-b",
        "--cookie",
        "-u",
        "--user",
        *_DATA_FLAGS,
    }
    for token in tokens[1:]:
        if skip_value:
            skip_value = False
            continue
        if token in value_options:
            skip_value = True
            continue
        if token.startswith("http://") or token.startswith("https://"):
            url = token
            break
    if not url:
        return None

    method = "GET"
    method_match = re.search(r"(?:-X|--request)\s+(POST|GET|PUT|PATCH|DELETE)", text, re.IGNORECASE)
    if method_match:
        method = method_match.group(1).upper()
    elif "-d" in text or "--data" in text:
        method = "POST"

    headers: dict[str, str] = {}
    for m in re.finditer(r"(?:-H|--header)\s+" + _quote_pattern(), text):
        raw = next((group for group in m.groups() if group is not None), "")
        _add_header(headers, raw)

    # Cookies: -b/--cookie may be a whole "name=value; name2=value2" string, and
    # may be repeated; -H "Cookie: ..." is already in ``headers``.
    cookie_parts: list[str] = []
    existing_cookie = next(
        (value for name, value in headers.items() if name.lower() == "cookie"), None
    )
    if existing_cookie:
        cookie_parts.append(existing_cookie)
    for m in re.finditer(r"(?:-b|--cookie)\s+" + _quote_pattern(), text):
        raw = next((group for group in m.groups() if group is not None), "")
        raw = raw.strip()
        if not raw or raw.startswith("@"):
            # -b @cookies.txt is a file reference, not a value to copy.
            continue
        cookie_parts.append(raw)
    if cookie_parts:
        headers = {name: value for name, value in headers.items() if name.lower() != "cookie"}
        headers["Cookie"] = "; ".join(part.strip().strip(";") for part in cookie_parts)

    # -u user:password is HTTP basic auth.
    basic_match = re.search(r"(?:-u|--user)\s+" + _quote_pattern(), text)
    if basic_match:
        raw = next((group for group in basic_match.groups() if group is not None), "")
        if raw and ":" in raw and not any(name.lower() == "authorization" for name in headers):
            token = base64.b64encode(raw.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"

    body_template = None
    data_pattern = r"(?:" + "|".join(re.escape(flag) for flag in _DATA_FLAGS) + r")\s+"
    data_match = re.search(data_pattern + _quote_pattern(), text, re.DOTALL)
    if data_match:
        data = _unquote(next((g for g in data_match.groups() if g is not None), ""))
        # Try to replace input with {{input}}
        # Common patterns
        for key in ["question", "input", "query", "message", "prompt"]:
            # Replace quoted values
            pattern = r'"' + key + r'"\s*:\s*"([^"]*)"'
            if re.search(pattern, data):
                data = re.sub(pattern, f'"{key}": {{input}}', data)
                break
        try:
            # Validate it's JSON-like
            json.loads(data.replace("{{input}}", '"test"'))
            body_template = data
        except Exception:
            body_template = '{"question": {{input}}}'

    if method == "POST" and body_template is None:
        body_template = '{"question": {{input}}}'

    return ParsedCurl(
        method=method,
        url=url,
        headers=headers,
        body_template=body_template,
        header_count=len(headers),
    )


def encrypt_headers(headers: dict[str, str]) -> str | None:
    """A header map as one encrypted blob for storage and run snapshots."""
    if not headers:
        return None
    return encrypt_key(json.dumps(headers, sort_keys=True))


def decrypt_headers(secret: str | None) -> dict[str, str]:
    """The header map back from its encrypted blob; empty when unreadable."""
    if not secret:
        return {}
    raw = decrypt_key(secret)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(name): str(value) for name, value in parsed.items()}
