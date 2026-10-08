from __future__ import annotations

from collections.abc import Iterator
from contextvars import ContextVar, Token
from typing import Any


class TraceRecorder:
    def __init__(self) -> None:
        self.steps: dict[str, Any] = {}

    def emit(self, name: str, value: Any) -> None:
        self.steps[name] = value


_active_recorder: ContextVar[TraceRecorder | None] = ContextVar(
    "greenlit_trace_recorder", default=None
)


class trace_context:
    def __init__(self) -> None:
        self.recorder = TraceRecorder()
        self._token: Token[TraceRecorder | None] | None = None

    def __enter__(self) -> TraceRecorder:
        self._token = _active_recorder.set(self.recorder)
        return self.recorder

    def __exit__(self, *_: object) -> None:
        if self._token is not None:
            _active_recorder.reset(self._token)


def emit_trace_step(name: str, value: Any) -> None:
    recorder = _active_recorder.get()
    if recorder is not None:
        recorder.emit(name, value)


def current_trace() -> TraceRecorder | None:
    return _active_recorder.get()


def trace_steps() -> Iterator[tuple[str, Any]]:
    recorder = _active_recorder.get()
    return iter(recorder.steps.items()) if recorder is not None else iter(())
