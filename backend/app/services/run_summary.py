"""A finished run explained in plain words (deterministic templates only).

No model, no network, no free text: every sentence is a template filled from the
run's own numbers, and the reasons come from the decision engine's own record
(``Decision.to_dict()``) rather than from a second copy of its rules. The same
function feeds the HTML export (:mod:`app.services.report`) and the run page's
``summary`` field, so the two cannot say different things.

A metric that was never measured is named, never scored: it is left out of the
weighted score, so it is not printed as 0.00 and never described as a failure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.decision import SUGGESTED_FIXES

# Fixed, reviewed advice keyed to the condition that produced it. Nothing here is
# written per run, and nothing here is generated.
RUN_NEXT_STEPS: dict[str, str] = {
    "no_valid_items": (
        "Check the connector, the endpoint URL and the request body, then run a smoke test."
    ),
    "no_metrics": "Make the app return an answer and its retrieved context, then run again.",
    "stopped_by_limit": (
        "Raise the case or token limit if the whole dataset matters, then run again."
    ),
    "judge_unsure": "Read the cases the judge was unsure about before trusting the verdict.",
    "judge_unavailable": "Check the judge provider and model, or run again without the judge.",
    "nothing_to_fix": "Nothing to fix: every gate passed and no metric was weak.",
}

MAX_NEXT_STEPS = 4

SAFETY_NOT_MEASURED = (
    "Safety was not measured on this run, so this summary claims nothing about it."
)


def _label(metric: str) -> str:
    """``answer_match`` reads as "answer match" in a sentence."""
    return metric.replace("_", " ")


def _format(value: float) -> str:
    return f"{value:.2f}"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _sentence(value: str) -> str:
    """A stored explanation as a sentence of its own."""
    if not value:
        return ""
    first = value[0].upper()
    body = first + value[1:]
    return body if body.endswith((".", "!", "?")) else body + "."


def _measured(metrics: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [metric for metric in metrics if metric.get("instrumented")]


def _thresholds(decision: Mapping[str, Any] | None) -> tuple[str, str]:
    if decision is None:
        return "", ""
    review = _number(decision.get("review_threshold"))
    go = _number(decision.get("go_threshold"))
    if review is None or go is None:
        return "", ""
    return _format(review), _format(go)


def _gate_names(
    metrics: Sequence[Mapping[str, Any]], decision: Mapping[str, Any] | None
) -> list[str]:
    if decision is not None:
        recorded = decision.get("hard_gate_failures")
        if isinstance(recorded, list) and recorded:
            return [str(name) for name in recorded]
    return [
        str(metric["name"])
        for metric in _measured(metrics)
        if metric.get("hard_gate") and not metric.get("passed")
    ]


def _headline(
    *,
    verdict: str,
    score: float | None,
    decision: Mapping[str, Any] | None,
    gates: Sequence[str],
    cases_total: int | None,
) -> str:
    review, go = _thresholds(decision)
    rule = decision.get("rule") if decision is not None else None
    scored = f"the weighted score was {_format(score)}" if score is not None else ""

    if verdict == "GO":
        if score is None:
            return "GreenLit says GO: no hard gate failed."
        return f"GreenLit says GO: {scored}, at or above the {go} go threshold."

    if verdict == "REVIEW":
        if rule == 3:
            what = f"the score of {_format(score)}" if score is not None else "the run"
            return (
                f"GreenLit says REVIEW: the judge could not be trusted, so {what}"
                " needs a person to look at it."
            )
        if score is None:
            return "GreenLit says REVIEW: the run could not be scored."
        return (
            f"GreenLit says REVIEW: {scored}, between the {review} review and {go} go thresholds."
        )

    if gates:
        listed = " and ".join(_label(name) for name in gates)
        if score is None:
            return f"GreenLit says NO-GO: the hard gate {listed} failed."
        return (
            f"GreenLit says NO-GO: the hard gate {listed} failed, so a weighted score of"
            f" {_format(score)} could not save it."
        )
    if score is None:
        if cases_total == 0:
            return (
                "GreenLit says NO-GO: the run produced no valid cases, so there is nothing"
                " to score."
            )
        return "GreenLit says NO-GO: no metric could be measured, so there is no score."
    return f"GreenLit says NO-GO: {scored}, below the {review} review threshold."


def _gate_reasons(metrics: Sequence[Mapping[str, Any]], gates: Sequence[str]) -> list[str]:
    reasons: list[str] = []
    for name in gates:
        metric = next((row for row in metrics if row.get("name") == name), None)
        if metric is None:
            reasons.append(f"The hard gate {_label(name)} failed.")
            continue
        threshold = _number(metric.get("threshold"))
        where = f" (needs {_format(threshold)})" if threshold is not None else ""
        score = _number(metric.get("score"))
        scored = f"scored {_format(score)}" if score is not None else "was not scored"
        reason = f"The hard gate {_label(name)} failed: it {scored}{where}."
        explanation = _sentence(_text(metric.get("explanation")))
        if explanation:
            reason += f" {explanation}"
        reasons.append(reason)
    return reasons


def _judge_reasons(judge: Mapping[str, Any] | None) -> list[str]:
    if not judge:
        return []
    reasons: list[str] = []
    unavailable = _number(judge.get("unavailable_items")) or 0.0
    unsure = _number(judge.get("low_confidence_items")) or 0.0
    disagreements = _number(judge.get("disagreements")) or 0.0
    tolerance = _number(judge.get("tolerance")) or 0.0
    if unavailable:
        reasons.append(
            f"The judge could not score {int(unavailable)} case(s), so not every answer"
            " was reviewed."
        )
    if unsure:
        reasons.append(
            f"The judge was unsure on {int(unsure)} case(s), so a person should read them."
        )
    if disagreements > tolerance:
        reasons.append(
            f"The judge and the human labels disagreed on {int(disagreements)} case(s)"
            f" (tolerance {int(tolerance)})."
        )
    return reasons


def _recorded_weak(decision: Mapping[str, Any] | None) -> list[tuple[str, float]]:
    recorded = decision.get("weak_metrics") if decision is not None else None
    if not isinstance(recorded, list):
        return []
    pairs: list[tuple[str, float]] = []
    for entry in recorded:
        if not isinstance(entry, dict):
            continue
        name = entry.get("metric")
        score = _number(entry.get("score"))
        if isinstance(name, str) and score is not None:
            pairs.append((name, score))
    return pairs


def _weakest(
    metrics: Sequence[Mapping[str, Any]], decision: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """The weak measured metrics, lowest first, exactly as the engine listed them."""
    pairs = _recorded_weak(decision)
    if decision is None:
        # An older run has no decision record: fall back to its own numbers.
        for metric in _measured(metrics):
            score = _number(metric.get("score"))
            if score is not None and score < 0.999:
                pairs.append((str(metric["name"]), score))
        pairs.sort(key=lambda pair: pair[1])
        pairs = pairs[:3]
    seen: set[str] = set()
    weak: list[dict[str, Any]] = []
    for name, score in pairs:
        if name in seen:
            continue
        seen.add(name)
        weak.append({"metric": name, "label": _label(name), "score": round(score, 4)})
    return weak


def _weakest_sentence(weak: Sequence[Mapping[str, Any]]) -> str:
    if not weak:
        return "No measured metric was weak."
    listed = ", ".join(f"{entry['label']} {_format(entry['score'])}" for entry in weak)
    return f"Weakest measured metrics: {listed}."


def _not_measured(metrics: Sequence[Mapping[str, Any]]) -> tuple[list[str], str]:
    names = [_label(str(metric["name"])) for metric in metrics if not metric.get("instrumented")]
    if not names:
        return [], ""
    listed = ", ".join(names)
    pronoun = "It is" if len(names) == 1 else "They are"
    return names, (
        f"Not measured on this run: {listed}. {pronoun} left out of the weighted score and"
        " not counted as zero."
    )


def _safety_sentence(metrics: Sequence[Mapping[str, Any]]) -> str:
    attacks = next((row for row in metrics if row.get("name") == "attack_resisted"), None)
    refusal = next((row for row in metrics if row.get("name") == "over_refusal"), None)
    if attacks is None and refusal is None:
        return SAFETY_NOT_MEASURED

    parts: list[str] = []
    if attacks is not None:
        raw_details = attacks.get("details")
        details: Mapping[str, Any] = raw_details if isinstance(raw_details, dict) else {}
        tried = _number(details.get("attacks"))
        resisted = _number(details.get("resisted"))
        if tried is None or tried == 0 or not attacks.get("instrumented"):
            parts.append("the safety attacks did not run, so nothing is claimed about leaks")
        else:
            leaked = int(tried - (resisted or 0.0))
            if leaked <= 0:
                parts.append(f"no leak was recorded in 0 of {int(tried)} attack cases")
            else:
                parts.append(f"a leak was recorded in {leaked} of {int(tried)} attack cases")
    if refusal is not None and refusal.get("instrumented"):
        raw_refusal = refusal.get("details")
        refusal_details: Mapping[str, Any] = raw_refusal if isinstance(raw_refusal, dict) else {}
        prompts = _number(refusal_details.get("prompts"))
        refused = _number(refusal_details.get("refused"))
        if prompts:
            parts.append(
                f"the app refused {int(refused or 0.0)} of {int(prompts)} harmless prompts"
            )
    if not parts:
        return SAFETY_NOT_MEASURED
    return "Safety: " + "; ".join(parts) + "."


def _next_steps(
    *,
    score: float | None,
    decision: Mapping[str, Any] | None,
    gates: Sequence[str],
    judge: Mapping[str, Any] | None,
    cases_total: int | None,
    state: str | None,
) -> list[str]:
    steps: list[str] = []

    def add(step: str) -> None:
        if step and step not in steps:
            steps.append(step)

    fixes = decision.get("suggested_fixes") if decision is not None else None
    if isinstance(fixes, list):
        for fix in fixes:
            if isinstance(fix, str) and fix.strip():
                add(fix.strip())
    if not steps:
        # Only when the engine itself suggested nothing, so its list stays first.
        for name, _score in _recorded_weak(decision):
            add(SUGGESTED_FIXES.get(name, ""))
    for name in gates:
        add(SUGGESTED_FIXES.get(name, ""))
    if cases_total == 0:
        add(RUN_NEXT_STEPS["no_valid_items"])
    elif score is None:
        add(RUN_NEXT_STEPS["no_metrics"])
    if state == "STOPPED_BY_LIMIT":
        add(RUN_NEXT_STEPS["stopped_by_limit"])
    if judge:
        if (_number(judge.get("low_confidence_items")) or 0.0) > 0:
            add(RUN_NEXT_STEPS["judge_unsure"])
        if (_number(judge.get("unavailable_items")) or 0.0) > 0:
            add(RUN_NEXT_STEPS["judge_unavailable"])
    if not steps:
        add(RUN_NEXT_STEPS["nothing_to_fix"])
    return steps[:MAX_NEXT_STEPS]


def build_run_summary(
    *,
    verdict: str | None,
    score: float | None,
    decision: Mapping[str, Any] | None,
    metrics: Sequence[Mapping[str, Any]],
    judge: Mapping[str, Any] | None,
    cases_total: int | None,
    state: str | None = None,
) -> dict[str, Any]:
    """Everything a reader needs in plain words, and nothing they must infer."""
    gates = _gate_names(metrics, decision)
    if verdict is None:
        headline = "GreenLit has no verdict for this run yet."
    else:
        headline = _headline(
            verdict=verdict,
            score=score,
            decision=decision,
            gates=gates,
            cases_total=cases_total,
        )

    reasons = _gate_reasons(metrics, gates)
    reasons.extend(_judge_reasons(judge))
    if decision is None and verdict is not None:
        reasons.append(
            "This run finished before the summary existed, so the rule it was decided by was"
            " not recorded; the verdict above is the one the engine stored."
        )

    weak = _weakest(metrics, decision)
    names, not_measured_sentence = _not_measured(metrics)

    return {
        "headline": headline,
        "reasons": reasons,
        "weakest": weak,
        "weakest_sentence": _weakest_sentence(weak),
        "not_measured": names,
        "not_measured_sentence": not_measured_sentence,
        "safety_sentence": _safety_sentence(metrics),
        "next_steps": _next_steps(
            score=score,
            decision=decision,
            gates=gates,
            judge=judge,
            cases_total=cases_total,
            state=state,
        ),
    }
