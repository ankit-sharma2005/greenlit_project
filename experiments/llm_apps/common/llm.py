"""A tiny OpenAI-compatible chat client, built on the pinned ``requests``.

Two providers are supported: a local Ollama (no key) and Groq (key from the
environment). A 429 or a timeout becomes :class:`ProviderUnavailable`, which the
apps turn into a clean 503 with ``Retry-After`` when the provider gave one. One
connection error is retried; a 429 is never retried. Nothing here logs a prompt,
a header or a key.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import requests

from .config import CONNECT_TIMEOUT_SECONDS, Settings


class LLMError(Exception):
    """The provider answered, but not with a usable chat completion."""


@dataclass
class ProviderUnavailable(Exception):
    """No answer was produced: 429, timeout or a refused connection."""

    reason: str
    retry_after: str | None = None

    def __str__(self) -> str:
        return self.reason


Message = dict[str, str]


class LLMClient:
    """One chat call or one streamed chat call, against an OpenAI-compatible API."""

    def __init__(
        self, settings: Settings, session: requests.Session | None = None
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.url = f"{settings.base_url}/chat/completions"

    # -- payloads ---------------------------------------------------------
    def _payload(self, messages: Sequence[Message], stream: bool) -> dict[str, Any]:
        return {
            "model": self.settings.model,
            "messages": list(messages),
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "stream": stream,
        }

    def _post(self, messages: Sequence[Message], stream: bool) -> requests.Response:
        headers = {"Content-Type": "application/json", **self.settings.auth_headers()}
        payload = self._payload(messages, stream)
        # Connecting is quick; only waiting for the answer may take minutes. For a
        # stream this read timeout applies between chunks, not to the whole stream.
        timeout = (CONNECT_TIMEOUT_SECONDS, self.settings.timeout_seconds)
        try:
            response = self.session.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=timeout,
                stream=stream,
            )
        except requests.ConnectionError as exc:
            # One retry, and only for a connection error: the request never left.
            try:
                response = self.session.post(
                    self.url,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                    stream=stream,
                )
            except (requests.ConnectionError, requests.Timeout) as second:
                raise ProviderUnavailable("provider_unavailable") from second
            del exc
        except requests.Timeout as exc:
            raise ProviderUnavailable("provider_unavailable") from exc

        if response.status_code == 429:
            raise ProviderUnavailable(
                "provider_unavailable", response.headers.get("Retry-After")
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                "provider_unavailable", response.headers.get("Retry-After")
            )
        if response.status_code >= 400:
            raise LLMError(f"provider answered HTTP {response.status_code}")
        return response

    # -- one answer -------------------------------------------------------
    def chat(self, messages: Sequence[Message]) -> str:
        response = self._post(messages, stream=False)
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("provider answered a body that is not JSON") from exc
        return _answer_from(body)

    # -- streamed answer ---------------------------------------------------
    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        """Yield answer pieces as they arrive.

        A provider that answers a streaming request with one JSON body (no
        ``text/event-stream``) is not an error: its answer is chunked here, so
        every caller always gets a stream and a final marker.
        """
        response = self._post(messages, stream=True)
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            try:
                answer = _answer_from(response.json())
            except ValueError as exc:
                raise LLMError("provider answered a body that is not JSON") from exc
            yield from _chunks(answer)
            return

        try:
            yield from self._sse_pieces(response)
        except requests.Timeout as exc:
            raise ProviderUnavailable("provider_unavailable") from exc
        except requests.ConnectionError as exc:
            raise ProviderUnavailable("provider_unavailable") from exc

    @staticmethod
    def _sse_pieces(response: requests.Response) -> Iterator[str]:
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
            piece = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(piece, str) and piece:
                yield piece


def _answer_from(body: Any) -> str:
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices:
        raise LLMError("provider answered without choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise LLMError("provider answered without message content")
    return content


def _chunks(answer: str, size: int = 32) -> Iterator[str]:
    for start in range(0, len(answer), size):
        piece = answer[start : start + size]
        if piece:
            yield piece
