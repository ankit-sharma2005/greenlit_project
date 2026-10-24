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

    def __init__(
        self, message: str, code: str = "connector_error", details: dict[str, Any] | None = None
    ):
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
    """Extract value from data using dotted path with list indexes."""
    if not path:
        return None
    current = data
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
                ) from e

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
                    "your app rejected the request: check API key/auth",
                    code="auth_error",
                    details={"status_code": response.status_code},
                )

            try:
                data = response.json()
            except Exception as e:
                raise ConnectorError(
                    "Response was not valid JSON",
                    code="invalid_json",
                ) from e

            # Extract answer
            output = extract_by_path(data, answer_path) if answer_path else None
            if output is None:
                # Try common paths
                for path in [
                    "answer",
                    "response",
                    "output",
                    "text",
                    "message",
                    "content",
                    "result",
                    "choices.0.message.content",
                ]:
                    output = extract_by_path(data, path)
                    if output is not None:
                        break
            if output is None or not isinstance(output, str):
                raise ConnectorError(
                    "wrong answer path (show real response to pick key)",
                    code="wrong_answer_path",
                    details={"response": data},
                )

            # Extract context
            context: list[str] | str = "not instrumented"
            for ctx_path in [
                "context",
                "contexts",
                "sources",
                "retrieved_context",
                "documents",
                "chunks",
            ]:
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
        except httpx.TimeoutException as e:
            latency_ms = int((time.time() - start) * 1000)
            raise ConnectorError(
                "increase the timeout or speed up the app",
                code="timeout",
            ) from e
        except ConnectorError:
            raise
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            raise ConnectorError(str(e), code="connector_error") from e

    def auto_detect(
        self,
        url: str,
        input_text: str = "Hello",
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 60,
        method: str = "POST",
    ) -> tuple[Trace, str, str | None, str | None]:
        """Try request shapes in order."""
        shapes = [
            ('{"question": {{input}}}', "question"),
            ('{"input": {{input}}}', "input"),
            ('{"query": {{input}}}', "query"),
            ('{"message": {{input}}}', "message"),
            ('{"prompt": {{input}}}', "prompt"),
        ]
        last_err = None
        for template, _shape_name in shapes:
            try:
                trace = self.render_and_send(
                    url=url,
                    body_template=template,
                    input_text=input_text,
                    headers=headers,
                    timeout_seconds=timeout_seconds,
                    method=method,
                    answer_path=None,
                )
                # Detect paths from trace.raw
                data = trace.raw if isinstance(trace.raw, dict) else {}
                detected_answer = None
                for path in [
                    "answer",
                    "response",
                    "output",
                    "text",
                    "message",
                    "content",
                    "result",
                    "choices.0.message.content",
                ]:
                    val = extract_by_path(data, path)
                    if isinstance(val, str) and val:
                        detected_answer = path
                        break
                detected_context = None
                for path in [
                    "context",
                    "contexts",
                    "sources",
                    "retrieved_context",
                    "documents",
                    "chunks",
                ]:
                    val = extract_by_path(data, path)
                    if val is not None:
                        detected_context = path
                        break
                return trace, template, detected_answer, detected_context
            except ConnectorError as e:
                last_err = e
                continue
        # Try OpenAI messages shape
        openai_template = '{"messages": [{"role": "user", "content": {{input}}}]}'
        try:
            trace = self.render_and_send(
                url=url,
                body_template=openai_template,
                input_text=input_text,
                headers=headers,
                timeout_seconds=timeout_seconds,
                method=method,
                answer_path=None,
            )
            data = trace.raw if isinstance(trace.raw, dict) else {}
            detected_answer = None
            for path in [
                "answer",
                "response",
                "output",
                "text",
                "message",
                "content",
                "result",
                "choices.0.message.content",
            ]:
                val = extract_by_path(data, path)
                if isinstance(val, str) and val:
                    detected_answer = path
                    break
            detected_context = None
            for path in [
                "context",
                "contexts",
                "sources",
                "retrieved_context",
                "documents",
                "chunks",
            ]:
                val = extract_by_path(data, path)
                if val is not None:
                    detected_context = path
                    break
            return trace, openai_template, detected_answer, detected_context
        except ConnectorError as e:
            last_err = e
        if last_err:
            raise last_err
        raise ConnectorError("Auto-detect failed", code="auto_detect_failed")


class PromptAppConnector:
    """Prompt app connector using injectable LLM gateway."""

    def __init__(self, llm_gateway: Any = None, chat: Any = None) -> None:
        if chat is not None:
            self.chat = chat
            self.llm = None
            return
        if llm_gateway is not None:
            self.llm = llm_gateway
            self.chat = None
            return
        from app.services.llm_gateway import LLMGateway

        self.llm = LLMGateway()
        self.chat = None

    def render_and_send(
        self,
        prompt: str,
        input_text: str,
        model: str = "gpt-4o-mini",
        system_prompt: str | None = None,
        temperature: float = 0.2,
    ) -> Trace:
        start = time.time()
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt.replace("{{input}}", input_text)})
            if self.chat is not None:
                result = self.chat(messages, model=model, params={"temperature": temperature})
            elif self.llm is not None and hasattr(self.llm, "chat"):
                # Try to be compatible with different signatures
                try:
                    result = self.llm.chat(messages=messages, model=model, params={"temperature": temperature})
                except TypeError:
                    try:
                        result = self.llm.chat(messages=messages, model=model)
                    except Exception:
                        try:
                            result = self.llm.chat(provider=None, messages=messages, temperature=temperature, model=model)
                        except Exception:
                            result = self.llm.chat(messages, model, {"temperature": temperature})
            else:
                raise ConnectorError("No chat function configured", code="connector_error")
            latency_ms = int((time.time() - start) * 1000)
            if isinstance(result, dict):
                content = result.get("content", "")
                tokens_in = result.get("tokens_in")
                tokens_out = result.get("tokens_out")
                raw = result
            elif isinstance(result, str):
                content = result
                tokens_in = None
                tokens_out = None
                raw = {"content": result}
            else:
                content = str(result)
                tokens_in = None
                tokens_out = None
                raw = {"content": content}
            return Trace(
                output=content if isinstance(content, str) else str(content),
                retrieved_context="not instrumented",
                tool_calls="not instrumented",
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error=None,
                raw=raw,
            )
        except ConnectorError:
            raise
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            raise ConnectorError(str(e), code="connector_error") from e


class UploadOutputsConnector:
    """Upload outputs connector for CSV/JSON files."""

    def render_and_send(self, csv_content: str, input_text: str = "") -> Trace:
        start = time.time()
        try:
            import csv
            import io

            f = io.StringIO(csv_content)
            reader = csv.DictReader(f)
            rows = list(reader)
            if not rows:
                raise ConnectorError("No rows found in CSV", code="empty_file")
            # Look for common answer columns
            answer_col = None
            for col in ["answer", "output", "response", "text", "result"]:
                if col in rows[0]:
                    answer_col = col
                    break
            if not answer_col:
                # Try any column that's not obviously metadata
                for col in rows[0]:
                    if col.lower() not in ["id", "input", "question", "query", "context"]:
                        answer_col = col
                        break
            if not answer_col:
                raise ConnectorError("Could not find answer column", code="missing_answer_column")
            output = str(rows[0].get(answer_col, ""))
            latency_ms = int((time.time() - start) * 1000)
            return Trace(
                output=output,
                retrieved_context="not instrumented",
                tool_calls="not instrumented",
                latency_ms=latency_ms,
                tokens_in=None,
                tokens_out=None,
                error=None,
                raw={"rows": rows, "answer_column": answer_col},
            )
        except ConnectorError:
            raise
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            raise ConnectorError(str(e), code="connector_error") from e
