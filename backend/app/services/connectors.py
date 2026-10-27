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
