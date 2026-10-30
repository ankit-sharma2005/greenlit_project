"""Run the built-in safety sets through a run's connector sender (spec 8.3).

The executor owns one ``Sender`` per run (the same callable that answers the
dataset cases). Reusing it here means the safety probes honour the run's saved
timeout, headers, target and model, instead of a second, drift-prone call path.

A run may choose which sets to send (the New Test page's Safety Set Selection).
The selection is validated when the run is created, so this module only filters:
an attack category nobody selected is never sent, and the harmless requests are
skipped when their set is off. Nothing is scored that was not sent — the metric
is reported as *not instrumented* with the reason instead of a green 1.0.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from app.safety.metrics import (
    ATTACK_RESISTED,
    DEFAULT_ATTACK_RESISTED_THRESHOLD,
    DEFAULT_OVER_REFUSAL_LIMIT,
    OVER_REFUSAL,
    attack_resisted_summary,
    attack_succeeded,
    over_refusal,
)
from app.safety.sets import (
    AttackSet,
    SafePromptSet,
    SafetySelection,
    load_attack_set,
    load_safe_prompt_set,
    resolve_safety_sets,
    safety_catalogue,
)
from app.services.connectors import Trace
from app.services.metrics import MetricResult, not_instrumented

Sender = Callable[[str], Trace]

DEFAULT_PROBE_WORKERS = 2

NO_ATTACK_SET_REASON = "no attack set was selected for this run"
NO_SAFE_PROMPT_REASON = "the harmless-request set was not selected for this run"


def probe_safety(
    sender: Sender,
    *,
    selection: SafetySelection | None = None,
    workers: int = DEFAULT_PROBE_WORKERS,
    attack_threshold: float = DEFAULT_ATTACK_RESISTED_THRESHOLD,
    over_refusal_limit: float = DEFAULT_OVER_REFUSAL_LIMIT,
) -> dict[str, MetricResult]:
    """Send the selected attacks and safe prompts through ``sender``.

    ``selection=None`` sends every set, which is what runs created before the
    selection existed recorded. A prompt that raises records no output: the app
    never said anything, so an attack cannot have leaked the marker and a
    harmless request was not refused (an error is what ``error_rate`` is for,
    not over-refusal).
    """
    chosen = selection if selection is not None else resolve_safety_sets(None)
    attack_set = load_attack_set()
    prompt_set = load_safe_prompt_set()

    selected_attacks: AttackSet = chosen.filtered_attack_set(attack_set)
    selected_prompts = (
        prompt_set
        if chosen.include_safe_prompts
        else SafePromptSet(version=prompt_set.version, prompts=())
    )

    attack_prompts = {case.id: case.prompt for case in selected_attacks.cases}
    safe_prompts = {item.id: item.prompt for item in selected_prompts.prompts}

    # Attack and safe prompts never overlap, but dedupe anyway so one prompt is
    # never sent twice if a future set reuses a wording.
    unique = list(dict.fromkeys([*attack_prompts.values(), *safe_prompts.values()]))
    outputs = _send_all(sender, unique, workers)

    attack_outputs = {case_id: outputs.get(text) for case_id, text in attack_prompts.items()}
    safe_outputs = {item_id: outputs.get(text) for item_id, text in safe_prompts.items()}

    metrics: dict[str, MetricResult] = {}
    if chosen.attack_categories:
        summary = attack_resisted_summary(selected_attacks, attack_outputs, attack_threshold)
        summary.details["selected_sets"] = list(chosen.ids)
        summary.details["sets"] = _per_set_findings(selected_attacks, attack_outputs)
        metrics[ATTACK_RESISTED] = summary
    else:
        metrics[ATTACK_RESISTED] = not_instrumented(ATTACK_RESISTED, NO_ATTACK_SET_REASON)

    if chosen.include_safe_prompts:
        metrics[OVER_REFUSAL] = over_refusal(selected_prompts, safe_outputs, over_refusal_limit)
    else:
        metrics[OVER_REFUSAL] = not_instrumented(OVER_REFUSAL, NO_SAFE_PROMPT_REASON)

    return metrics


def _per_set_findings(
    attack_set: AttackSet, outputs: dict[str, str | None]
) -> list[dict[str, object]]:
    """How each selected set fared, so the Safety section can name them.

    Only sets that are part of ``attack_set`` appear: the caller already filtered
    by the run's selection, so this never invents a set that was not sent.
    """
    titles = {item.id: (item.name, item.critical_count) for item in safety_catalogue()}
    findings: list[dict[str, object]] = []
    for category in dict.fromkeys(case.category for case in attack_set.cases):
        cases = [case for case in attack_set.cases if case.category == category]
        failed = [case.id for case in cases if attack_succeeded(case, outputs.get(case.id))]
        critical = [
            case.id
            for case in cases
            if case.critical and attack_succeeded(case, outputs.get(case.id))
        ]
        name, critical_count = titles.get(category, (category, 0))
        findings.append(
            {
                "id": category,
                "name": name,
                "cases": len(cases),
                "failed": failed,
                "critical_failures": critical,
                "critical_cases": critical_count,
            }
        )
    return findings


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
