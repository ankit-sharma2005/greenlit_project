import asyncio

from app.tracing import current_trace, emit_trace_step, trace_context, trace_steps


def test_trace_context_captures_steps_and_restores_parent_context() -> None:
    assert current_trace() is None

    with trace_context() as outer:
        emit_trace_step("prompt", "outer prompt")
        assert current_trace() is outer
        assert list(trace_steps()) == [("prompt", "outer prompt")]

        with trace_context() as inner:
            emit_trace_step("retrieval", ["chunk"])
            assert current_trace() is inner
            assert list(trace_steps()) == [("retrieval", ["chunk"])]

        assert current_trace() is outer
        emit_trace_step("output", "answer")
        assert list(trace_steps()) == [
            ("prompt", "outer prompt"),
            ("output", "answer"),
        ]

    assert current_trace() is None
    assert list(trace_steps()) == []


def test_trace_context_isolated_between_async_tasks() -> None:
    async def record_step(name: str, value: str) -> tuple[str, ...]:
        with trace_context():
            emit_trace_step(name, value)
            await asyncio.sleep(0)
            recorder = current_trace()
            assert recorder is not None
            return tuple(recorder.steps)

    async def run_tasks() -> tuple[tuple[str, ...], tuple[str, ...]]:
        left, right = await asyncio.gather(
            record_step("left", "L"),
            record_step("right", "R"),
        )
        return left, right

    assert asyncio.run(run_tasks()) == (("left",), ("right",))
