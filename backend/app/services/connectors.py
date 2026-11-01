"""Connector interface and implementations (M3)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.error_kinds import HTTP_ERROR, kind_for_code
from app.services.target_error import redact_snippet, target_of
from app.utils.request_client import (
    RequestClient,
    RequestDeadlineExceededError,
    RequestInterruptedError,
)

# One case may not hold a worker for longer than this, however politely the
# target keeps saying "not now".
DEFAULT_ITEM_BUDGET_SECONDS = 150.0

# A streamed answer must stay bounded: a chatbot that never stops talking is a
# setup problem, not a bigger answer.
MAX_ANSWER_BYTES = 100 * 1024
RESPONSE_FORMATS = ("json", "sse", "ndjson", "text")

# Where streamed pieces usually live, in the order auto-detect tries them.
_STREAM_TEXT_PATHS = (
    "choices.0.delta.content",
    "choices.0.text",
    "choices.0.message.content",
    "delta.content",
    "delta.text",
    "token",
    "content",
    "text",
    "answer",
    "response",
    "output",
    "message",
)


class ConnectorError(Exception):
    """Connector failed with a friendly message."""

    def __init__(
        self, message: str, code: str = "connector_error", details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    @property
    def kind(self) -> str:
        """The structured failure kind, so the metrics need not read the text."""
        return kind_for_code(self.code)


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
    # Only streamed answers can say when the first byte arrived.
    time_to_first_byte_ms: int | None = None
    # Polite-rate bookkeeping: how many retries preceded the final attempt and
    # how long the waits between them took. ``latency_ms`` is the final attempt
    # alone, so a retried case never looks slow.
    retry_count: int = 0
    waited_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "retrieved_context": self.retrieved_context,
            "tool_calls": self.tool_calls,
            "latency_ms": self.latency_ms,
            "time_to_first_byte_ms": self.time_to_first_byte_ms,
            "retry_count": self.retry_count,
            "waited_ms": self.waited_ms,
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


def _text_piece(value: Any) -> str | None:
    """One streamed piece as text; a list of strings is joined, numbers stringified."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list) and all(isinstance(entry, str) for entry in value):
        return "".join(value)
    return None


def _http_failure(status: int, snippet: str, target: str) -> ConnectorError:
    """A non-2xx answer as the same structured failure for json and streams."""
    code = "http_error"
    message = f"target returned HTTP {status}"
    if status == 404:
        code = "not_found"
        message = "your app answered but this path does not exist"
    elif status in (401, 403):
        code = "auth_error"
        # A pasted cURL carries a session that expires: say what to do next.
        message = (
            "your app rejected the request (HTTP "
            f"{status}): the session or token may have expired; paste a fresh cURL"
        )
    return ConnectorError(
        message,
        code=code,
        details={
            "status_code": status,
            "target": target,
            "snippet": snippet,
            "message": message,
            "kind": HTTP_ERROR,
        },
    )


def streamed_piece(payload: Any, content_path: str | None) -> str | None:
    """The answer text inside one streamed event.

    An explicit path wins; otherwise the OpenAI-style delta, a plain ``token``
    field and the usual answer fields are tried. A non-JSON event is its own
    text (the plain ``data:`` fallback).
    """
    if isinstance(payload, str):
        return payload
    if content_path:
        return _text_piece(extract_by_path(payload, content_path))
    for path in _STREAM_TEXT_PATHS:
        piece = _text_piece(extract_by_path(payload, path))
        if piece is not None:
            return piece
    return None


class HttpConnector:
    """HTTP endpoint connector with shared request function.

    ``max_concurrency``, ``min_delay_ms`` and ``max_retries`` are the polite-rate
    settings a real chatbot needs: one request at a time, a pause between them,
    and a few retries when the target says 429/502/503/504.
    """

    def __init__(
        self,
        allow_private: bool = False,
        *,
        max_concurrency: int = 1,
        min_delay_ms: int = 500,
        max_retries: int = 3,
        item_budget_seconds: float = DEFAULT_ITEM_BUDGET_SECONDS,
        interrupt: threading.Event | None = None,
    ):
        self.max_concurrency = max(1, int(max_concurrency))
        self.min_delay_ms = max(0, int(min_delay_ms))
        self.max_retries = max(0, int(max_retries))
        self.item_budget_seconds = max(0.001, float(item_budget_seconds))
        # Set by the worker when the run is cancelled: retry waits stop early.
        self.interrupt = interrupt
        self.client = RequestClient(
            allow_private_targets=allow_private, max_retries=self.max_retries
        )
        self._concurrency = threading.BoundedSemaphore(self.max_concurrency)
        self._pace_lock = threading.Lock()
        self._last_request_started = 0.0

    def _wait_for_turn(self) -> None:
        """Respect the minimum gap between request starts (never inside a lock)."""
        if self.min_delay_ms <= 0:
            return
        with self._pace_lock:
            gap = self.min_delay_ms / 1000.0
            waited = time.monotonic() - self._last_request_started
            if waited < gap:
                time.sleep(gap - waited)
            self._last_request_started = time.monotonic()

    def render_and_send(
        self,
        url: str,
        body_template: str,
        input_text: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 60,
        method: str = "POST",
        answer_path: str | None = None,
        response_format: str = "json",
        stream_content_path: str | None = None,
    ) -> Trace:
        """Shared function for test call and run items."""
        start = time.time()
        deadline = time.monotonic() + self.item_budget_seconds
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

            target = target_of(url)
            fmt = response_format if response_format in RESPONSE_FORMATS else "json"

            if fmt != "json":
                return self._stream_response(
                    url=url,
                    body=body,
                    headers=headers,
                    method=method,
                    timeout_seconds=timeout_seconds,
                    response_format=fmt,
                    stream_content_path=stream_content_path,
                    start=start,
                    deadline=deadline,
                )

            # Make request: at most ``max_concurrency`` in flight, with the
            # configured pause between starts and retries for a busy target.
            with self._concurrency:
                self._wait_for_turn()
                response = self.client.request(
                    method=method,
                    url=url,
                    json=body,
                    headers=headers,
                    timeout=timeout_seconds,
                    max_retries=self.max_retries,
                    interrupt=self.interrupt,
                    deadline=deadline,
                )

            # The final attempt's own latency: the waits between retries are
            # recorded separately, so a recovered case is never called slow.
            waited_ms = int(self.client.last_waited_seconds * 1000)
            latency_ms = max(0, int((time.time() - start) * 1000) - waited_ms)
            retry_count = self.client.last_retry_count
            status = response.status_code
            # A test double may not model the body; a real httpx response does.
            snippet = redact_snippet(getattr(response, "text", ""))

            # Any non-2xx answer is a target failure, never a missing answer: a
            # 422 must not be reported as "wrong answer path" (the run would
            # then look like a quality problem instead of a setup problem).
            if not 200 <= status < 300:
                raise _http_failure(status, snippet, target)

            try:
                data = response.json()
            except Exception as e:
                raise ConnectorError(
                    "Response was not valid JSON",
                    code="invalid_json",
                    details={
                        "status_code": status,
                        "target": target,
                        "snippet": snippet,
                        "message": "Response was not valid JSON",
                    },
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
                retry_count=retry_count,
                waited_ms=waited_ms,
            )
        except RequestInterruptedError as e:
            raise ConnectorError(
                "this case was cancelled before the target answered",
                code="cancelled",
                details={"target": target_of(url), "message": "cancelled"},
            ) from e
        except RequestDeadlineExceededError as e:
            budget = self.item_budget_seconds
            message = f"this case hit the {budget:g} s budget and was stopped"
            raise ConnectorError(
                message,
                code="timeout",
                details={
                    "target": target_of(url),
                    "timeout_seconds": budget,
                    "message": message,
                },
            ) from e
        except httpx.TimeoutException as e:
            # The attempt's own timeout was capped by the item budget: say which
            # one ran out, so a slow case is not blamed on the setting alone.
            if time.monotonic() >= deadline - 0.05:
                budget = self.item_budget_seconds
                message = f"this case hit the {budget:g} s budget and was stopped"
                raise ConnectorError(
                    message,
                    code="timeout",
                    details={
                        "target": target_of(url),
                        "timeout_seconds": budget,
                        "message": message,
                    },
                ) from e
            raise ConnectorError(
                "increase the timeout or speed up the app",
                code="timeout",
                details={
                    "target": target_of(url),
                    "timeout_seconds": timeout_seconds,
                    "message": f"the app did not answer within {timeout_seconds} s",
                },
            ) from e
        except httpx.ConnectError as e:
            # The app is not listening at all, which is not a timeout.
            raise ConnectorError(
                f"could not connect to the app: {str(e)[:200]}",
                code="connection_error",
                details={"target": target_of(url), "message": "could not connect to the app"},
            ) from e
        except ConnectorError:
            raise
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            raise ConnectorError(str(e), code="connector_error") from e

    def _stream_response(
        self,
        *,
        url: str,
        body: Any,
        headers: dict[str, str] | None,
        method: str,
        timeout_seconds: int,
        response_format: str,
        stream_content_path: str | None,
        start: float,
        deadline: float | None = None,
    ) -> Trace:
        """Read an SSE/NDJSON/plain-text answer and join its pieces."""
        target = target_of(url)
        with self._concurrency:
            self._wait_for_turn()
            with self.client.stream(
                method=method,
                url=url,
                json=body,
                headers=headers,
                timeout=timeout_seconds,
                max_retries=self.max_retries,
                interrupt=self.interrupt,
                deadline=deadline,
            ) as response:
                status = response.status_code
                if not 200 <= status < 300:
                    response.read()
                    raise _http_failure(status, redact_snippet(response.text), target)
                output, ttfb_ms, byte_count = self._collect_stream(
                    response,
                    response_format=response_format,
                    content_path=stream_content_path,
                    timeout_seconds=timeout_seconds,
                    start=start,
                    target=target,
                )
        waited_ms = int(self.client.last_waited_seconds * 1000)
        latency_ms = max(0, int((time.time() - start) * 1000) - waited_ms)
        if not output.strip():
            raise ConnectorError(
                "the stream finished without any answer text; "
                "check the response format or the stream answer path",
                code="wrong_answer_path",
                details={
                    "target": target,
                    "message": "the stream finished without any answer text",
                },
            )
        return Trace(
            output=output,
            retrieved_context="not instrumented",
            tool_calls="not instrumented",
            latency_ms=latency_ms,
            tokens_in=None,
            tokens_out=None,
            error=None,
            raw={
                "response_format": response_format,
                "bytes": byte_count,
                "time_to_first_byte_ms": ttfb_ms,
                "retry_count": self.client.last_retry_count,
                "waited_ms": waited_ms,
            },
            time_to_first_byte_ms=ttfb_ms,
            retry_count=self.client.last_retry_count,
            waited_ms=waited_ms,
        )

    def _collect_stream(
        self,
        response: httpx.Response,
        *,
        response_format: str,
        content_path: str | None,
        timeout_seconds: int,
        start: float,
        target: str,
    ) -> tuple[str, int | None, int]:
        """Join streamed pieces, enforcing the total timeout and the size cap."""
        deadline = start + timeout_seconds
        pieces: list[str] = []
        size = 0
        ttfb_ms: int | None = None

        def mark_first_byte() -> None:
            nonlocal ttfb_ms
            if ttfb_ms is None:
                ttfb_ms = int((time.time() - start) * 1000)

        def check_deadline() -> None:
            if time.time() > deadline:
                raise ConnectorError(
                    f"the stream did not finish within {timeout_seconds} s",
                    code="timeout",
                    details={
                        "target": target,
                        "timeout_seconds": timeout_seconds,
                        "message": f"the stream did not finish within {timeout_seconds} s",
                    },
                )

        def add(text: str) -> None:
            nonlocal size
            if not text:
                return
            size += len(text.encode("utf-8"))
            if size > MAX_ANSWER_BYTES:
                raise ConnectorError(
                    f"the streamed answer grew past {MAX_ANSWER_BYTES // 1024} KB and was cut",
                    code="response_too_large",
                    details={
                        "target": target,
                        "message": (
                            f"the streamed answer grew past {MAX_ANSWER_BYTES // 1024} KB; "
                            "check that the app stops its answer"
                        ),
                    },
                )
            pieces.append(text)

        def add_event(raw: str) -> None:
            stripped = raw.strip()
            if not stripped or stripped == "[DONE]":
                return
            try:
                payload: Any = json.loads(stripped)
            except json.JSONDecodeError:
                # A plain data: event keeps its own whitespace (" world").
                payload = raw
            piece = streamed_piece(payload, content_path)
            if piece:
                add(piece)

        if response_format == "text":
            for chunk in response.iter_bytes():
                check_deadline()
                mark_first_byte()
                add(chunk.decode("utf-8", errors="replace"))
            return "".join(pieces), ttfb_ms, size

        if response_format == "sse":
            data_lines: list[str] = []

            def flush() -> None:
                if data_lines:
                    add_event("\n".join(data_lines))
                    data_lines.clear()

            for line in response.iter_lines():
                check_deadline()
                mark_first_byte()
                if line == "":
                    flush()
                elif line.startswith(":"):
                    # A keepalive comment is not part of the answer.
                    continue
                elif line.startswith("data:"):
                    value = line[5:]
                    data_lines.append(value[1:] if value.startswith(" ") else value)
                # event:, id: and retry: carry no answer text.
            flush()
            return "".join(pieces), ttfb_ms, size

        # NDJSON: one JSON object (or plain line) per line.
        for line in response.iter_lines():
            check_deadline()
            mark_first_byte()
            add_event(line)
        return "".join(pieces), ttfb_ms, size

    def auto_detect(
        self,
        url: str,
        input_text: str = "Hello",
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 60,
        method: str = "POST",
        response_format: str = "json",
        stream_content_path: str | None = None,
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
                    response_format=response_format,
                    stream_content_path=stream_content_path,
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
                response_format=response_format,
                stream_content_path=stream_content_path,
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
                    result = self.llm.chat(
                        messages=messages, model=model, params={"temperature": temperature}
                    )
                except TypeError:
                    try:
                        result = self.llm.chat(messages=messages, model=model)
                    except Exception:
                        try:
                            result = self.llm.chat(
                                provider=None,
                                messages=messages,
                                temperature=temperature,
                                model=model,
                            )
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
    """Upload outputs connector for CSV/JSON files (M6d).

    The file holds the app's outputs for a set of inputs. The connection test
    validates the file and detects its columns; the run executor matches each
    uploaded row to an approved dataset item by id or by input text and scores
    the result (spec section 9).

    Supported columns (case-insensitive, first match wins):

    * id — row identifier used to match the uploaded file to dataset items;
    * input / question / prompt / query — the input the app was given;
    * output / actual_answer / actual / response / prediction / completion — the
      app's output for that input;
    * retrieved_context / context / contexts / retrieved — what the app retrieved;
    * latency_ms / latency / duration_ms — end-to-end latency in milliseconds;
    * tokens_in / prompt_tokens / input_tokens — input token count;
    * tokens_out / completion_tokens / output_tokens — output token count.

    Only ``input`` and ``output`` are required. Rows with no matching dataset
    item are reported as failed cases, not dropped.
    """

    _INPUT_ALIASES = ("input", "question", "prompt", "query")
    _OUTPUT_ALIASES = (
        "output",
        "actual_answer",
        "actual",
        "response",
        "prediction",
        "completion",
    )
    _ID_ALIASES = ("id", "row_id", "case_id", "item_id")
    _CONTEXT_ALIASES = ("retrieved_context", "context", "contexts", "retrieved")
    _LATENCY_ALIASES = ("latency_ms", "latency", "duration_ms")
    _TOKENS_IN_ALIASES = ("tokens_in", "prompt_tokens", "input_tokens")
    _TOKENS_OUT_ALIASES = ("tokens_out", "completion_tokens", "output_tokens")

    @staticmethod
    def _first_column(rows: list[dict[str, str]], aliases: tuple[str, ...]) -> str | None:
        """Return the first present column name from a set of aliases."""
        if not rows:
            return None
        lowered = {key.strip().lower(): key for key in rows[0]}
        for alias in aliases:
            if alias in lowered:
                return lowered[alias]
        return None

    @classmethod
    def detect_columns(
        cls, rows: list[dict[str, str]], overrides: dict[str, str] | None = None
    ) -> dict[str, str | None]:
        """Detect column roles from the file's header row, with optional overrides."""
        detected = {
            "id": cls._first_column(rows, cls._ID_ALIASES),
            "input": cls._first_column(rows, cls._INPUT_ALIASES),
            "output": cls._first_column(rows, cls._OUTPUT_ALIASES),
            "retrieved_context": cls._first_column(rows, cls._CONTEXT_ALIASES),
            "latency_ms": cls._first_column(rows, cls._LATENCY_ALIASES),
            "tokens_in": cls._first_column(rows, cls._TOKENS_IN_ALIASES),
            "tokens_out": cls._first_column(rows, cls._TOKENS_OUT_ALIASES),
        }
        if overrides and rows:
            available = {k.strip().lower() for k in rows[0]}
            for key, value in overrides.items():
                if (value and value.strip().lower() in available) or value:
                    detected[key] = value.strip()
        return detected

    @classmethod
    def parse_file(
        cls, csv_content: str, overrides: dict[str, str] | None = None
    ) -> tuple[str, list[dict[str, str]], dict[str, str | None]]:
        """Parse a CSV or JSON upload file.

        Returns ``(file_format, rows, detected_columns)``.
        """
        text = csv_content.strip()
        if not text:
            raise ConnectorError("The uploaded file is empty.", code="empty_file")

        # JSON first: a JSON file is either an array of objects or a single object.
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ConnectorError(
                    f"The JSON file could not be parsed: {exc.msg} (at position {exc.pos}).",
                    code="invalid_json",
                ) from exc
            if not isinstance(parsed, list):
                raise ConnectorError(
                    "The JSON file must be an array of objects, one row per object.",
                    code="invalid_json_shape",
                )
            if not parsed:
                raise ConnectorError("The JSON file is an empty array.", code="empty_file")
            if not isinstance(parsed[0], dict):
                raise ConnectorError(
                    "Each element in the JSON array must be an object with string values.",
                    code="invalid_json_shape",
                )
            rows = [{str(k): str(v) for k, v in row.items()} for row in parsed]
            return "json", rows, cls.detect_columns(rows, overrides)

        # CSV: header row plus data rows.
        import csv
        import io

        f = io.StringIO(text)
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows:
            # Could be a header-only CSV or unparseable; try harder.
            f.seek(0)
            first_line = f.readline().strip()
            if first_line:
                raise ConnectorError(
                    "The CSV file has a header but no data rows. Add at least one row.",
                    code="empty_file",
                )
            raise ConnectorError("The CSV file could not be parsed.", code="invalid_csv")
        return "csv", rows, cls.detect_columns(rows, overrides)

    def render_and_send(
        self, csv_content: str, input_text: str = "", overrides: dict[str, str] | None = None
    ) -> Trace:
        """Connection-test validation: parse the file and return a sample trace."""
        start = time.time()
        try:
            file_format, rows, columns = self.parse_file(csv_content, overrides)
            input_col = columns["input"]
            output_col = columns["output"]
            if not input_col:
                raise ConnectorError(
                    "Could not find an input column. Name it input, question, prompt or query.",
                    code="missing_input_column",
                )
            if not output_col:
                raise ConnectorError(
                    "Could not find an output column. Name it output, actual_answer, "
                    "response or completion.",
                    code="missing_output_column",
                )
            first = rows[0]
            output = str(first.get(output_col, "")).strip()
            latency_col = columns["latency_ms"]
            tokens_in_col = columns["tokens_in"]
            tokens_out_col = columns["tokens_out"]
            context_col = columns["retrieved_context"]

            def _int(value: str | None) -> int | None:
                if value is None or value == "":
                    return None
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    return None

            latency_ms = _int(first.get(latency_col)) if latency_col else None
            tokens_in = _int(first.get(tokens_in_col)) if tokens_in_col else None
            tokens_out = _int(first.get(tokens_out_col)) if tokens_out_col else None
            context: list[str] | str | None = None
            if context_col:
                raw = first.get(context_col)
                if raw:
                    if "," in raw:
                        context = [part.strip() for part in raw.split(",")]
                    else:
                        context = [str(raw)]

            latency_ms = latency_ms or int((time.time() - start) * 1000)
            return Trace(
                output=output or "",
                retrieved_context=context if context is not None else "not instrumented",
                tool_calls="not instrumented",
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error=None,
                raw={
                    "file_format": file_format,
                    "row_count": len(rows),
                    "columns": columns,
                    "sample_row": first,
                },
            )
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(str(exc), code="connector_error") from exc


def match_uploaded_rows(
    dataset_items: list[tuple[int, str, dict[str, str]]],
    rows: list[dict[str, str]],
    columns: dict[str, str | None],
) -> dict[int, dict[str, Any]]:
    """Match uploaded rows to dataset items by id, then by input text.

    ``dataset_items`` is a list of ``(row_index, input_text, item_data)`` tuples
    from the approved dataset version.

    Returns a mapping from dataset ``row_index`` to the matched row's parsed
    output fields. Dataset items with no match are simply absent from the result.
    """

    def _int(value: str | None) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    input_col = columns.get("input")
    output_col = columns.get("output")
    id_col = columns.get("id")
    context_col = columns.get("retrieved_context")
    latency_col = columns.get("latency_ms")
    tokens_in_col = columns.get("tokens_in")
    tokens_out_col = columns.get("tokens_out")

    # Build lookup by id first (most reliable), then by input text.
    by_id: dict[str, dict[str, Any]] = {}
    by_input: dict[str, dict[str, Any]] = {}

    for row in rows:
        normalized = {str(key).strip().lower(): str(value).strip() for key, value in row.items()}
        entry: dict[str, Any] = {
            "output": str(normalized.get(output_col, "")).strip() if output_col else "",
            "retrieved_context": None,
            "latency_ms": _int(normalized.get(latency_col)) if latency_col else None,
            "tokens_in": _int(normalized.get(tokens_in_col)) if tokens_in_col else None,
            "tokens_out": _int(normalized.get(tokens_out_col)) if tokens_out_col else None,
        }
        if context_col and normalized.get(context_col):
            raw = normalized[context_col]
            entry["retrieved_context"] = (
                [part.strip() for part in raw.split(",") if part.strip()] if "," in raw else [raw]
            )
        if id_col and normalized.get(id_col):
            by_id[normalized[id_col]] = entry
        if input_col and normalized.get(input_col):
            by_input[normalized[input_col].lower()] = entry

    matched: dict[int, dict[str, Any]] = {}
    for row_index, input_text, item_data in dataset_items:
        chosen: dict[str, Any] | None = None
        # Prefer id match when the dataset has an id column and the item carries one.
        if id_col:
            item_id = str(item_data.get(id_col, "")).strip()
            if item_id:
                chosen = by_id.get(item_id)
        # Fall back to input-text match.
        if chosen is None:
            chosen = by_input.get(input_text.lower()) or by_id.get(input_text)
        if chosen is not None:
            matched[row_index] = chosen
    return matched
