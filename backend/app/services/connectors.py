"""Connector interface and implementations (M3)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.utils.request_client import RequestClient


class ConnectorError(Exception):
    """Connector failed with a friendly message."""

    def __init__(self, message: str, code: str = "connector_error", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


@dataclass
class Trace:
    output: str
    retrieved_context: list[str] | str
    tool_calls: list[Any] | str
    latency_ms: int
    tokens_in: int | None
    tokens_out: int | None
    error: str | None
    raw: dict[str, Any] | str

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "retrieved_context": self.retrieved_context,
            "tool_calls": self.tool_calls,
            "latency_ms": self.latency_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "error": self.error,
            "raw": self.raw,
        }


def render_body_template(template: str, input_text: str) -> str:
    """Replace {{input}} with JSON-encoded string (quotes included)."""
    input_json = json.dumps(input_text)
    # Avoid double replacement issues
    result = template.replace("{{input}}", input_json)
    return result


def extract_by_path(data: Any, path: str | None) -> Any:
    """Extract value from data using dotted path with list indexes like choices.0.message.content."""
    if not path:
        return None
    current = data
    # Split by dots but handle array indices
    parts: list[str] = []
    for part in path.split("."):
        # Check if it's array index like choices[0] or just choices.0
        if "[" in part and part.endswith("]"):
            name = part[: part.index("[")]
            idx_str = part[part.index("[") + 1 : -1]
            if name:
                if isinstance(current, dict):
                    current = current.get(name)
                else:
                    return None
            try:
                idx = int(idx_str)
                if isinstance(current, list) and len(current) > idx:
                    current = current[idx]
                else:
                    return None
            except ValueError:
                return None
        else:
            # Check if part is all digits (array index)
            if part.isdigit() and isinstance(current, list):
                idx = int(part)
                if len(current) > idx:
                    current = current[idx]
                else:
                    return None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None
    return current


class HttpConnector:
    """HTTP endpoint connector with shared request function."""

    def __init__(self, allow_private: bool = False):
        self.client = RequestClient(allow_private_targets=allow_private)

    def render_and_send(
        self,
        url: str,
        body_template: str,
        input_text: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 60,
        method: str = "POST",
        answer_path: str | None = None,
    ) -> Trace:
        """Shared function for test call and run items."""
        start = time.time()
        try:
            # Render body template
            rendered = render_body_template(body_template, input_text)
            try:
                body = json.loads(rendered)
            except json.JSONDecodeError as e:
                raise ConnectorError(
                    f"Invalid JSON in body template at position {e.pos}: {e.msg}",
                    code="template_error",
                )

            # Make request
            response = self.client.request(
                method=method,
                url=url,
                json=body,
                headers=headers,
                timeout=timeout_seconds,
            )

            latency_ms = int((time.time() - start) * 1000)

            if response.status_code == 404:
                raise ConnectorError(
                    "your app answered but this path does not exist",
                    code="not_found",
                    details={"status_code": 404},
                )
            if response.status_code in (401, 403):
                raise ConnectorError(
                    "your app rejected the request: check the API key or the app's CSRF/auth setting",
                    code="auth_error",
                    details={"status_code": response.status_code},
                )

            try:
                data = response.json()
            except Exception:
                raise ConnectorError(
                    "Response was not valid JSON",
                    code="invalid_json",
                )

            # Extract answer
            output = extract_by_path(data, answer_path) if answer_path else None
            if output is None:
                # Try common paths
                for path in ["answer", "response", "output", "text", "message", "content", "result", "choices.0.message.content"]:
                    output = extract_by_path(data, path)
                    if output is not None:
                        break
            if output is None or not isinstance(output, str):
                raise ConnectorError(
                    "wrong answer path (show the real response and let the user click the right key)",
                    code="wrong_answer_path",
                    details={"response": data},
                )

            # Extract context
            context: list[str] | str = "not instrumented"
            for ctx_path in ["context", "contexts", "sources", "retrieved_context", "documents", "chunks"]:
                ctx = extract_by_path(data, ctx_path)
                if ctx is not None:
                    if isinstance(ctx, list):
                        context = [str(c) for c in ctx]
                    elif isinstance(ctx, str):
                        context = [ctx]
                    break

            return Trace(
                output=output,
                retrieved_context=context,
                tool_calls="not instrumented",
                latency_ms=latency_ms,
                tokens_in=None,
                tokens_out=None,
                error=None,
                raw=data,
            )
        except httpx.TimeoutException:
            latency_ms = int((time.time() - start) * 1000)
            raise ConnectorError(
                "increase the timeout or speed up the app",
                code="timeout",
            )
        except ConnectorError:
            raise
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            raise ConnectorError(str(e), code="connector_error")
