"""Parse curl commands into request parts (M3)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class ParsedCurl:
    method: str
    url: str
    headers: dict[str, str]
    body_template: str | None
    header_count: int


def parse_curl(curl: str) -> ParsedCurl | None:
    if not curl or not curl.strip().lower().startswith("curl"):
        return None

    text = curl.strip()

    # Extract URL
    url_match = re.search(r"curl\s+(?:-[^\s]+\s+)*[\"']([^\"']+)[\"']", text)
    if not url_match:
        url_match = re.search(r"curl\s+(?:-[^\s]+\s+)*([^\s]+)", text)
    if not url_match:
        return None
    url = url_match.group(1)
    if url.startswith("-"):
        return None

    method = "GET"
    method_match = re.search(r"-X\s+(POST|GET|PUT|PATCH|DELETE)", text, re.IGNORECASE)
    if method_match:
        method = method_match.group(1).upper()
    elif "-d" in text or "--data" in text:
        method = "POST"

    headers: dict[str, str] = {}
    for m in re.finditer(r"-H\s+[\"']([^\"']+)[\"']", text):
        h = m.group(1)
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()

    body_template = None
    data_match = re.search(r"(?:-d|--data(?:-raw)?)\s+[\"'](.+?)[\"']", text, re.DOTALL)
    if data_match:
        data = data_match.group(1)
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
