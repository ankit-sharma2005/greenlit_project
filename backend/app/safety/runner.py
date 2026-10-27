"""Run the built-in safety sets through a run's connector sender (spec 8.3).

The executor owns one ``Sender`` per run (the same callable that answers the
dataset cases). Reusing it here means the safety probes honour the run's saved
timeout, headers, target and model, instead of a second, drift-prone call path.

Only the recorded outputs cross back: :func:`probe_safety` returns the two
metric results, so the caller never has to know how the sets are shaped.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from app.safety.metrics import (
    DEFAULT_ATTACK_RESISTED_THRESHOLD,
    DEFAULT_OVER_REFUSAL_LIMIT,
    safety_metrics,
)
from app.safety.sets import load_attack_set, load_safe_prompt_set
from app.services.connectors import Trace
from app.services.metrics import MetricResult

Sender = Callable[[str], Trace]

DEFAULT_PROBE_WORKERS = 2


def probe_safety(
    sender: Sender,
    *,
    workers: int = DEFAULT_PROBE_WORKERS,
    attack_threshold: float = DEFAULT_ATTACK_RESISTED_THRESHOLD,
    over_refusal_limit: float = DEFAULT_OVER_REFUSAL_LIMIT,
) -> dict[str, MetricResult]:
    """Send every built-in attack and safe prompt through ``sender``.

    A prompt that raises records no output: the app never said anything, so an
    attack cannot have leaked the marker and a harmless request was not refused
    (an error is what ``error_rate`` is for, not over-refusal).
    """
    attack_set = load_attack_set()
    prompt_set = load_safe_prompt_set()

    attack_prompts = {case.id: case.prompt for case in attack_set.cases}
    safe_prompts = {item.id: item.prompt for item in prompt_set.prompts}

    # Attack and safe prompts never overlap, but dedupe anyway so one prompt is
    # never sent twice if a future set reuses a wording.
    unique = list(dict.fromkeys([*attack_prompts.values(), *safe_prompts.values()]))
    outputs = _send_all(sender, unique, workers)

    attack_outputs = {case_id: outputs.get(text) for case_id, text in attack_prompts.items()}
    safe_outputs = {item_id: outputs.get(text) for item_id, text in safe_prompts.items()}
    return safety_metrics(
        attack_set,
        attack_outputs,
        prompt_set,
        safe_outputs,
        attack_threshold=attack_threshold,
        over_refusal_limit=over_refusal_limit,
    )


def _send_all(sender: Sender, prompts: Sequence[str], workers: int) -> dict[str, str | None]:
    """Send each prompt once and map the prompt text to the app's output."""
    outputs: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for prompt, output in zip(
            prompts, pool.map(lambda text: _send_one(sender, text), prompts), strict=True
        ):
            outputs[prompt] = output
    return outputs


def _send_one(sender: Sender, prompt: str) -> str | None:
    """One probe; a failing call records no output rather than failing the run."""
    try:
        trace = sender(prompt)
    except Exception:  # one bad probe must not fail the run (spec 8.1)
        return None
    output = trace.output
    return output if isinstance(output, str) else None
