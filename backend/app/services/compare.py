"""Compare detail and comparability, built on the existing baseline comparison.

The stored ``services.regression.compare`` result (PASS/WARN/BLOCK) keeps its
meaning exactly: it is what the run card and the report show. This module adds a
richer, read-only view for one pair of runs, plus the plain classification
("regressed" / "improved" / "unchanged") that CI needs:

* comparability first — same dataset version, criteria profile *and* the
  fingerprint of its weights and thresholds, safety set versions and test types.
  Anything different is a reason string and no deltas at all;
* verdict change (GO > REVIEW > NO-GO), weighted score delta, per-metric deltas
  where a metric unmeasured on either side is "not measured" and excluded, hard
  gates that newly failed or passed, latency p50/p95 by the same
  ``operations.percentile`` the charts use, and per-case flips by row index;
* a classification that never contradicts the stored status: BLOCK is always
  "regressed", and "improved" is only possible when the stored status is PASS.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import Run
from app.services import regression
from app.services.criteria import CriteriaError, get_profile
from app.services.operations import percentile
from app.services.run_repository import get_metric_results, list_run_items

REGRESSED = "regressed"
IMPROVED = "improved"
UNCHANGED = "unchanged"

DEFAULT_TOLERANCE = 0.05
MAX_TOLERANCE = 0.5

VERDICT_RANK = {"NO_GO": 0, "REVIEW": 1, "GO": 2}

NOISE_CAUTION = (
    "This target is model-backed, so a few flipped cases can be run-to-run noise. "
    "Repeat the run before concluding that the app regressed; this comparison cannot "
    "tell a real change from sampling luck."
)


class CompareError(Exception):
    """A compare request that cannot be honoured, with an HTTP status."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class RunFacts:
    """What decides comparability, read from one run's own record."""

    dataset_version_id: uuid.UUID | None
    criteria_profile: str
    criteria_version: str
    safety_versions: tuple[str, ...]
    test_types: tuple[str, ...]


@dataclass(frozen=True)
class CaseState:
    """One case, with the two facts the flip list needs and one for new errors."""

    row_index: int
    input: str
    passed: bool
    error: bool


def criteria_version(profile_key: str) -> str:
    """A stable fingerprint of the profile's rules, for "same criteria" checks."""
    try:
        profile = get_profile(profile_key)
    except CriteriaError:
        return profile_key
    payload = json.dumps(profile.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _safety_versions(ids: Any) -> tuple[str, ...]:
    """The versions of the safety sets a run used, resolved from the snapshot ids."""
    from app.safety.sets import SafetySetError, resolve_safety_sets

    if not isinstance(ids, list) or not ids:
        return ()
    try:
        selection = resolve_safety_sets([str(item) for item in ids])
    except SafetySetError:
        return tuple(str(item) for item in ids)
    sets = getattr(selection, "sets", None)
    if sets is None:
        return tuple(sorted(str(item) for item in ids))
    return tuple(sorted(str(getattr(item, "version", item)) for item in sets))


def facts_of(run: Run) -> RunFacts:
    """Everything comparability needs, from a run's stored fields."""
    snapshot: Mapping[str, Any] = run.settings_snapshot or {}
    raw_types = snapshot.get("test_types")
    test_types = (
        tuple(sorted(str(item) for item in raw_types)) if isinstance(raw_types, list) else ()
    )
    profile = run.criteria_profile or ""
    return RunFacts(
        dataset_version_id=run.dataset_version_id,
        criteria_profile=profile,
        criteria_version=criteria_version(profile),
        safety_versions=_safety_versions(snapshot.get("safety_sets")),
        test_types=test_types,
    )


def comparability(baseline: RunFacts, current: RunFacts) -> list[str]:
    """Every reason the two runs cannot be compared, in a fixed order."""
    reasons: list[str] = []
    if baseline.dataset_version_id != current.dataset_version_id:
        reasons.append("the dataset version is different")
    if baseline.criteria_profile != current.criteria_profile:
        reasons.append(
            f"the criteria profile is different ({baseline.criteria_profile} vs "
            f"{current.criteria_profile})"
        )
    elif baseline.criteria_version != current.criteria_version:
        reasons.append("the criteria profile's rules changed between the runs")
    if baseline.safety_versions != current.safety_versions:
        left = ", ".join(baseline.safety_versions) or "none"
        right = ", ".join(current.safety_versions) or "none"
        reasons.append(f"the safety set versions are different ({left} vs {right})")
    if baseline.test_types != current.test_types:
        left = ", ".join(baseline.test_types) or "none"
        right = ", ".join(current.test_types) or "none"
        reasons.append(f"the test types are different ({left} vs {right})")
    return reasons


def _target_url(run: Run) -> str:
    snapshot = run.settings_snapshot or {}
    for key in ("target", "mcp_url"):
        value = snapshot.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def is_deterministic_target(run: Run) -> bool:
    """True for a target whose answers do not depend on a model.

    ``upload_outputs`` replays recorded answers, and the catalog's math solver is
    arithmetic with no model; everything else may vary run to run.
    """
    from app.services.demo_catalog import CATALOG

    snapshot = run.settings_snapshot or {}
    if snapshot.get("entry_point") == "upload_outputs":
        return True
    target = _target_url(run)
    solver = next((entry for entry in CATALOG if entry.id == "math-solver"), None)
    return solver is not None and target.rstrip("/") == solver.url.rstrip("/")


def _case_states(session: Session, run: Run) -> dict[int, CaseState]:
    """Per-case pass/fail and whether the case itself errored."""
    failed_items: dict[uuid.UUID, bool] = {}
    for row in get_metric_results(session, run.id):
        if row.run_item_id is None or not row.instrumented:
            continue
        failed_items[row.run_item_id] = failed_items.get(row.run_item_id, True) and bool(row.passed)
    states: dict[int, CaseState] = {}
    for item in list_run_items(session, run.id):
        states[item.row_index] = CaseState(
            row_index=item.row_index,
            input=item.input_text,
            passed=(
                item.state == "completed"
                and item.output is not None
                and failed_items.get(item.id, True)
            ),
            error=bool(item.error) or item.state == "error",
        )
    return states


def _metric_rows(session: Session, run: Run) -> dict[str, Any]:
    """The run-level metric rows by name (per-item rows are not metrics)."""
    return {row.name: row for row in get_metric_results(session, run.id) if row.run_item_id is None}


def _latency(session: Session, run: Run) -> dict[str, float | None]:
    """p50/p95 over the cases' own timings, the same percentile as the charts."""
    latencies = [
        float(item.latency_ms)
        for item in list_run_items(session, run.id)
        if isinstance(item.latency_ms, int) and item.latency_ms >= 0
    ]
    return {
        "p50": percentile(latencies, 0.5),
        "p95": percentile(latencies, 0.95),
        "samples": len(latencies),
    }


def _delta(baseline: float | None, current: float | None) -> float | None:
    if baseline is None or current is None:
        return None
    return round(current - baseline, 4)


def _flips(
    baseline_cases: Mapping[int, CaseState], current_cases: Mapping[int, CaseState]
) -> dict[str, list[dict[str, Any]]]:
    pass_to_fail: list[dict[str, Any]] = []
    fail_to_pass: list[dict[str, Any]] = []
    new_errors: list[dict[str, Any]] = []
    for row_index in sorted(current_cases):
        before = baseline_cases.get(row_index)
        now = current_cases[row_index]
        if before is None:
            continue
        entry = {"row_index": row_index, "input": now.input}
        if before.passed and not now.passed:
            pass_to_fail.append(entry)
        if not before.passed and now.passed:
            fail_to_pass.append(entry)
        if now.error and not before.error:
            new_errors.append(entry)
    only_baseline = [
        {"row_index": row, "input": baseline_cases[row].input}
        for row in sorted(set(baseline_cases) - set(current_cases))
    ]
    only_current = [
        {"row_index": row, "input": current_cases[row].input}
        for row in sorted(set(current_cases) - set(baseline_cases))
    ]
    return {
        "pass_to_fail": pass_to_fail,
        "fail_to_pass": fail_to_pass,
        "new_errors": new_errors,
        "only_in_baseline": only_baseline,
        "only_in_current": only_current,
    }


def _verdict_view(baseline: Run, current: Run) -> dict[str, Any]:
    before = baseline.verdict
    now = current.verdict
    rank_before = VERDICT_RANK.get(before or "")
    rank_now = VERDICT_RANK.get(now or "")
    direction = "same"
    if rank_before is not None and rank_now is not None:
        if rank_now < rank_before:
            direction = "worse"
        elif rank_now > rank_before:
            direction = "better"
    return {"baseline": before, "current": now, "direction": direction}


def _classification(
    *,
    existing_status: str,
    verdict: Mapping[str, Any],
    hard_gates_newly_failed: Sequence[str],
    hard_gates_newly_passed: Sequence[str],
    score_delta: float | None,
    tolerance: float,
    flipped_to_fail: int,
    flipped_to_pass: int,
    deterministic: bool,
) -> tuple[str, str]:
    """The plain label, derived from the stored status plus the extra evidence."""
    reasons: list[str] = []
    regressed = False
    if existing_status == regression.STATUS_BLOCK:
        regressed = True
        reasons.append("the stored comparison is BLOCK")
    if verdict["direction"] == "worse":
        regressed = True
        reasons.append(f"the verdict went {verdict['baseline']} → {verdict['current']}")
    if hard_gates_newly_failed:
        regressed = True
        reasons.append("a hard gate newly failed: " + ", ".join(hard_gates_newly_failed))
    if score_delta is not None and score_delta < -tolerance:
        regressed = True
        reasons.append(f"the score dropped {abs(score_delta):.2f}, beyond {tolerance:.2f}")
    if deterministic and flipped_to_fail:
        regressed = True
        reasons.append(f"{flipped_to_fail} case(s) flipped pass → fail on a deterministic target")
    if regressed:
        return REGRESSED, "; ".join(reasons) + "."

    improved = False
    upgraded: list[str] = []
    if verdict["direction"] == "better":
        improved = True
        upgraded.append(f"the verdict went {verdict['baseline']} → {verdict['current']}")
    if hard_gates_newly_passed:
        improved = True
        upgraded.append("a hard gate newly passed: " + ", ".join(hard_gates_newly_passed))
    if score_delta is not None and score_delta > tolerance:
        improved = True
        upgraded.append(f"the score rose {score_delta:.2f}, beyond {tolerance:.2f}")
    if deterministic and flipped_to_pass:
        improved = True
        upgraded.append(f"{flipped_to_pass} case(s) flipped fail → pass on a deterministic target")
    if improved and existing_status == regression.STATUS_PASS:
        return IMPROVED, "; ".join(upgraded) + "."
    if improved:
        # The stored status already flagged something, so this is never "improved".
        return UNCHANGED, (
            "Nothing regressed, but the stored comparison is "
            f"{existing_status}, so this is not called improved."
        )
    return UNCHANGED, "Nothing moved beyond the tolerance in either direction."


def compare_detail(
    session: Session,
    current: Run,
    baseline_run: Run,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """The whole comparison as plain data; comparable=false has no deltas."""
    if tolerance < 0 or tolerance > MAX_TOLERANCE:
        raise CompareError("The tolerance must be between 0 and 0.5.", status=422)

    reasons = comparability(facts_of(baseline_run), facts_of(current))
    baseline_metrics = _metric_rows(session, baseline_run)
    current_metrics = _metric_rows(session, current)
    baseline_cases = _case_states(session, baseline_run)
    current_cases = _case_states(session, current)
    flips = _flips(baseline_cases, current_cases)
    verdict = _verdict_view(baseline_run, current)
    deterministic = is_deterministic_target(current)

    detail: dict[str, Any] = {
        "comparable": not reasons,
        "reasons": reasons,
        "baseline_run_id": str(baseline_run.id),
        "baseline_run_name": baseline_run.name,
        "current_run_id": str(current.id),
        "current_run_name": current.name,
        "tolerance": tolerance,
        "deterministic_target": deterministic,
        "noise_caution": None if deterministic else NOISE_CAUTION,
        "verdict": verdict,
        "verdict_changed": verdict["direction"] != "same",
        "score": {
            "baseline": baseline_run.score,
            "current": current.score,
            "delta": _delta(baseline_run.score, current.score),
        },
    }
    if reasons:
        # No deltas at all: the numbers would invite a comparison that is not valid.
        detail.update(
            {
                "classification": None,
                "classification_reason": None,
                "existing_status": None,
                "metrics": [],
                "hard_gates": {"newly_failed": [], "newly_passed": []},
                "latency": {"baseline": None, "current": None, "delta": None},
                "cases": flips,
            }
        )
        return detail

    names = sorted(set(baseline_metrics) | set(current_metrics))
    metrics: list[dict[str, Any]] = []
    newly_failed: list[str] = []
    newly_passed: list[str] = []
    for name in names:
        before = baseline_metrics.get(name)
        now = current_metrics.get(name)
        measured = (
            before is not None
            and now is not None
            and bool(before.instrumented)
            and bool(now.instrumented)
        )
        entry: dict[str, Any] = {
            "name": name,
            "status": "measured" if measured else "not measured",
            "baseline": before.score if measured and before is not None else None,
            "current": now.score if measured and now is not None else None,
            "delta": None,
            "passed_before": bool(before.passed) if before is not None else None,
            "passed_now": bool(now.passed) if now is not None else None,
            "hard_gate": bool((before and before.hard_gate) or (now and now.hard_gate)),
        }
        if measured and before is not None and now is not None:
            entry["delta"] = _delta(before.score, now.score)
            if entry["hard_gate"]:
                if before.passed and not now.passed:
                    newly_failed.append(name)
                if not before.passed and now.passed:
                    newly_passed.append(name)
        metrics.append(entry)

    # The stored status, from the exact same points the existing comparison uses.
    stored = regression.compare(
        [
            regression.MetricPoint(
                name=row.name,
                score=row.score,
                passed=bool(row.passed),
                instrumented=bool(row.instrumented),
                hard_gate=bool(row.hard_gate),
            )
            for row in baseline_metrics.values()
        ],
        [
            regression.MetricPoint(
                name=row.name,
                score=row.score,
                passed=bool(row.passed),
                instrumented=bool(row.instrumented),
                hard_gate=bool(row.hard_gate),
            )
            for row in current_metrics.values()
        ],
        [
            regression.CasePoint(row_index=case.row_index, input=case.input, passed=case.passed)
            for case in baseline_cases.values()
        ],
        [
            regression.CasePoint(row_index=case.row_index, input=case.input, passed=case.passed)
            for case in current_cases.values()
        ],
    )

    score_delta = detail["score"]["delta"]
    classification, classification_reason = _classification(
        existing_status=stored.status,
        verdict=verdict,
        hard_gates_newly_failed=newly_failed,
        hard_gates_newly_passed=newly_passed,
        score_delta=score_delta if isinstance(score_delta, float) else None,
        tolerance=tolerance,
        flipped_to_fail=len(flips["pass_to_fail"]),
        flipped_to_pass=len(flips["fail_to_pass"]),
        deterministic=deterministic,
    )

    baseline_latency = _latency(session, baseline_run)
    current_latency = _latency(session, current)

    detail.update(
        {
            "classification": classification,
            "classification_reason": classification_reason,
            "existing_status": stored.status,
            "metrics": metrics,
            "hard_gates": {"newly_failed": newly_failed, "newly_passed": newly_passed},
            "latency": {
                "baseline": baseline_latency,
                "current": current_latency,
                "delta": {
                    "p50": _delta(baseline_latency["p50"], current_latency["p50"]),
                    "p95": _delta(baseline_latency["p95"], current_latency["p95"]),
                },
            },
            "cases": flips,
        }
    )
    return detail
