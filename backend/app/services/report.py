"""Run reports (spec 8.5): one result rendered as self-contained HTML, JSON or CSV.

The three renderers share a single document built from the run, its items, its
metrics and the dataset version it scored against, so an export cannot disagree
with the verdict card. Two rules matter more than the layout:

* **No secret leaves the box.** A run's settings snapshot is the one place its
  request headers are stored; the report redacts every header value and replaces
  the uploaded rows with a note, while provider keys are never in the snapshot at
  all. An exported file can be handed to somebody else.
* **Everything in the document is untrusted text.** HTML is escaped and a CSV
  cell that starts with a formula character is prefixed with a quote, so a case
  whose answer begins with ``=`` cannot execute in a spreadsheet.

The document is plain data, which is what lets the JSON export be the full
result and keeps the tests readable: no HTML parsing needed to assert content.
"""

from __future__ import annotations

import csv
import html
import io
import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, DatasetItem, DatasetVersion, Provider, Run, RunItem
from app.services.operations import (
    compute_operations,
    prices_from_metadata,
    samples_from_items,
)
from app.services.run_repository import get_metric_results, list_run_items

REPORT_VERSION = "1.0"
PROJECT_NAME = "Default project"
FORMATS: tuple[str, ...] = ("html", "json", "csv")

REDACTED = "[redacted]"
UPLOADED_ROWS_NOTE = "[omitted: the uploaded outputs are in the case table below]"

SAFETY_ATTACKS = "attack_resisted"
SAFETY_OVER_REFUSAL = "over_refusal"

# Characters that make a spreadsheet evaluate a cell instead of showing it
# (OWASP CSV injection). The single quote is what Excel and Sheets need.
_FORMULA_CHARS = ("=", "+", "-", "@")
_CAMPAIGN_CHARS = ("\t", "\r")

_EXPECTED_KEYS = ("expected_answer", "expected", "answer", "output")

# Inline stylesheet for the HTML export. It is a constant with one declaration
# per line so the markup stays inside the line limit and the file needs no
# external CSS (and therefore no network) to render.
_REPORT_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 32px;
  font: 14px/1.5 -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  color: #16181d;
  background: #ffffff;
}
h1 { font-size: 22px; margin: 0 0 4px; }
h2 {
  font-size: 15px;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: #4b5563;
  margin: 28px 0 8px;
}
.brand { font-weight: 700; letter-spacing: -.02em; font-size: 18px; }
.brand span { color: #16a34a; }
.muted { color: #6b7280; }
.verdict {
  display: flex;
  gap: 32px;
  align-items: baseline;
  flex-wrap: wrap;
  margin: 12px 0;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}
.verdict__word { font-size: 28px; font-weight: 700; }
.go { color: #15803d; }
.review { color: #b45309; }
.no-go { color: #b91c1c; }
.big { font-size: 22px; font-weight: 600; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 4px; }
th, td {
  text-align: left;
  padding: 7px 9px;
  border-bottom: 1px solid #e5e7eb;
  vertical-align: top;
}
th {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: #6b7280;
}
dl { display: grid; grid-template-columns: 220px 1fr; gap: 6px 16px; margin: 8px 0; }
dt { color: #6b7280; }
dd { margin: 0; word-break: break-word; }
.pass { color: #15803d; }
.fail { color: #b91c1c; }
.skip { color: #6b7280; }
pre { white-space: pre-wrap; word-break: break-word; margin: 0; font: inherit; }
footer { margin-top: 32px; color: #9ca3af; font-size: 12px; }
@media print {
  body { padding: 0; }
  h2 { break-after: avoid; }
  tr { break-inside: avoid; }
}
"""


def sanitized_settings(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The settings a run executed with, with secrets and bulk data removed."""
    cleaned: dict[str, Any] = {}
    for key, value in snapshot.items():
        if key == "headers":
            headers = value if isinstance(value, dict) else {}
            cleaned[key] = {str(name): REDACTED for name in sorted(headers)}
        elif key == "headers_encrypted":
            # A pasted cURL's headers: the blob is never exported either.
            cleaned[key] = REDACTED
        elif key == "csv":
            cleaned[key] = UPLOADED_ROWS_NOTE
        else:
            cleaned[key] = value
    return cleaned


def csv_cell(value: object) -> str:
    """A CSV field that cannot be evaluated as a formula when opened."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_CHARS):
        return "'" + text
    if text.startswith(_CAMPAIGN_CHARS):
        return "'" + text
    return text


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _expected_map(session: Session, run: Run) -> tuple[dict[int, str], dict[str, str]]:
    """The golden answers of the dataset version this run scored against.

    Dataset rows are 0-based while run items are 1-based, so the index is
    offset by one; an input-text match is tried first because it survives a
    dataset that was regenerated in a different order.
    """
    if run.dataset_version_id is None:
        return {}, {}
    rows = (
        session.execute(
            select(DatasetItem)
            .where(DatasetItem.dataset_version_id == run.dataset_version_id)
            .order_by(DatasetItem.row_index)
        )
        .scalars()
        .all()
    )
    by_index: dict[int, str] = {}
    by_input: dict[str, str] = {}
    for row in rows:
        data = {str(key).strip().lower(): value for key, value in (row.data or {}).items()}
        expected = None
        for key in _EXPECTED_KEYS:
            if key in data:
                expected = _text(data[key])
                if expected is not None:
                    break
        if expected is None:
            continue
        by_index[row.row_index] = expected
        inputs = [_text(data.get("input")), _text(data.get("question"))]
        for input_text in inputs:
            if input_text:
                by_input[input_text.strip().lower()] = expected
    return by_index, by_input


def _dataset_block(session: Session, run: Run) -> dict[str, Any] | None:
    if run.dataset_id is None:
        return None
    dataset = session.get(Dataset, run.dataset_id)
    version = (
        session.get(DatasetVersion, run.dataset_version_id) if run.dataset_version_id else None
    )
    if dataset is None:
        return None
    return {
        "name": dataset.name,
        "version": version.version_no if version is not None else None,
        "content_hash": (version.content_hash if version is not None else dataset.content_hash),
        "rows": version.row_count if version is not None else None,
        "generated": bool(version.generated) if version is not None else False,
    }


def _provider_block(session: Session, snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Which model answered: the saved provider, named, never its key."""
    raw_id = snapshot.get("provider_id")
    if not isinstance(raw_id, str) or not raw_id:
        return None
    try:
        provider_id = uuid.UUID(raw_id)
    except ValueError:
        return None
    provider = session.get(Provider, provider_id)
    if provider is None:
        return None
    return {
        "name": provider.name,
        "kind": provider.kind,
        "model": provider.model_name,
    }


def _case_rows(session: Session, run: Run, items: list[RunItem]) -> list[dict[str, Any]]:
    by_index, by_input = _expected_map(session, run)
    cases: list[dict[str, Any]] = []
    for item in items:
        expected = by_input.get(item.input_text.strip().lower())
        if expected is None:
            expected = by_index.get(item.row_index - 1) or by_index.get(item.row_index)
        meta = item.trace if isinstance(item.trace, dict) else {}
        raw_detail = meta.get("error_detail")
        detail = raw_detail if isinstance(raw_detail, dict) else {}
        status = detail.get("status")
        cases.append(
            {
                "row_index": item.row_index,
                "input": item.input_text,
                "expected": expected or "",
                "output": item.output or "",
                "state": item.state,
                "latency_ms": item.latency_ms,
                "tokens_in": item.tokens_in,
                "tokens_out": item.tokens_out,
                "reason": item.error or "",
                # What actually happened at the target, when it failed.
                "error_kind": detail.get("kind") or meta.get("error_kind"),
                "http_status": status if isinstance(status, int) else None,
                "target": detail.get("target") or None,
                "error_snippet": detail.get("snippet") or None,
                "error_summary": detail.get("summary") or None,
            }
        )
    return cases


def _setup_problem(cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A run where every case failed is a setup problem, not a quality result.

    Returning this as its own block lets every format say the same thing first:
    nothing was scored, so a score of 0 would be a lie about the app.
    """
    if not cases:
        return None
    failed = [case for case in cases if case["state"] == "failed"]
    if len(failed) != len(cases):
        return None
    statuses = sorted(
        {int(case["http_status"]) for case in failed if isinstance(case.get("http_status"), int)}
    )
    kinds = sorted({str(case.get("error_kind")) for case in failed if case.get("error_kind")})
    if statuses:
        detail = ", ".join(f"HTTP {status}" for status in statuses)
    elif kinds:
        detail = ", ".join(kinds)
    else:
        detail = "no status was recorded"
    target = next((case["target"] for case in failed if case.get("target")), None)
    where = f" at {target}" if target else ""
    return {
        "failed": len(failed),
        "total": len(cases),
        "detail": detail,
        "target": target,
        "line": (
            f"Setup problem: {len(failed)} of {len(cases)} requests failed ({detail}{where}). "
            "This is not a quality result."
        ),
    }


def _stored_setup_problem(snapshot: Mapping[str, Any]) -> dict[str, Any] | None:
    """The setup-problem block the worker stored when a pre-flight failed."""
    stored = snapshot.get("setup_problem")
    if not isinstance(stored, dict) or not stored.get("line"):
        return None
    return dict(stored)


def _metric_block(session: Session, run: Run) -> list[dict[str, Any]]:
    rows = get_metric_results(session, run.id)
    metrics: list[dict[str, Any]] = []
    for row in rows:
        metrics.append(
            {
                "name": row.name,
                "score": row.score,
                "passed": bool(row.passed),
                "instrumented": bool(row.instrumented),
                # The report says "not instrumented" instead of printing a 0.00
                # nobody measured; a 0 here would read as a failure.
                "state": (
                    ("pass" if row.passed else "fail") if row.instrumented else "not instrumented"
                ),
                "weight": row.weight,
                "threshold": row.threshold,
                "hard_gate": bool(row.hard_gate),
                "explanation": row.explanation,
                "details": dict(row.details or {}),
            }
        )
    return metrics


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(entry) for entry in value]


def _safety_block(metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The built-in probe results as their own section (spec 8.3)."""
    attacks = next((metric for metric in metrics if metric["name"] == SAFETY_ATTACKS), None)
    over_refusal = next(
        (metric for metric in metrics if metric["name"] == SAFETY_OVER_REFUSAL), None
    )
    if attacks is None and over_refusal is None:
        return None

    attack_details = attacks["details"] if attacks is not None else {}
    refusal_details = over_refusal["details"] if over_refusal is not None else {}
    tried = _number(attack_details.get("attacks")) or 0.0
    resisted = _number(attack_details.get("resisted")) or 0.0
    probed = _number(attack_details.get("probed"))
    instrumented = bool(attacks["instrumented"]) if attacks is not None else False

    return {
        "instrumented": instrumented,
        "attacks_tried": int(tried),
        "attacks_resisted": int(resisted),
        "attacks_probed": int(probed) if probed is not None else None,
        "critical_failures": _strings(attack_details.get("critical_failures")),
        "leaked_marker_cases": _strings(attack_details.get("leaked_marker_cases")),
        "over_refusal_share": _number(refusal_details.get("over_refusal_share")),
        "safe_prompts": int(_number(refusal_details.get("prompts")) or 0),
        "safe_prompts_refused": int(_number(refusal_details.get("refused")) or 0),
        "set_version": attack_details.get("set_version") or refusal_details.get("set_version"),
        "explanation": attacks["explanation"] if attacks is not None else "",
    }


def _permission_block(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Who allowed testing this target, or None for a local app."""
    if "permission_confirmed" not in snapshot:
        return None
    reference = snapshot.get("permission_reference")
    return {
        "confirmed": bool(snapshot.get("permission_confirmed")),
        "reference": str(reference) if reference else None,
        "safety_attacks_confirmed": bool(snapshot.get("safety_attacks_confirmed")),
    }


def _judge_block(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    raw = snapshot.get("judge")
    if not isinstance(raw, dict):
        return None
    return {
        "model": raw.get("judge_model"),
        "provider": raw.get("judge_provider_name"),
        "profile": raw.get("judge_profile_name"),
        "rubric_version": raw.get("judge_rubric_version"),
        "prompt_template_hash": raw.get("judge_prompt_hash"),
        "temperature": raw.get("judge_temperature"),
        "max_tokens": raw.get("judge_max_tokens"),
        "max_cases": raw.get("judge_max_cases"),
        "case_total": _number(raw.get("judge_case_total")),
        "capped_items": _number(raw.get("judge_capped_items")),
        "graded_items": _number(raw.get("judge_graded_items")),
        "unavailable_items": _number(raw.get("judge_unavailable_items")),
        "low_confidence_items": _number(raw.get("judge_low_confidence_items")),
    }


def _regression_block(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """The stored baseline comparison, if the run finished after one was set."""
    raw = snapshot.get("regression")
    if not isinstance(raw, dict):
        return None
    deltas = raw.get("metric_deltas")
    cases = raw.get("regressed_cases")
    return {
        "status": raw.get("status"),
        "reason": raw.get("reason"),
        "baseline_run_id": raw.get("baseline_run_id"),
        "baseline_run_name": raw.get("baseline_run_name"),
        "metric_tolerance": raw.get("metric_tolerance"),
        "case_tolerance": raw.get("case_tolerance"),
        "regressed_metrics": list(raw.get("regressed_metrics") or []),
        "metric_deltas": [delta for delta in deltas if isinstance(delta, dict)]
        if isinstance(deltas, list)
        else [],
        "regressed_cases": [case for case in cases if isinstance(case, dict)]
        if isinstance(cases, list)
        else [],
    }


def build_report(session: Session, run: Run) -> dict[str, Any]:
    """The full result of one run as plain data, for every renderer."""
    snapshot = dict(run.settings_snapshot or {})
    items = list_run_items(session, run.id)
    metrics = _metric_block(session, run)
    cases = _case_rows(session, run, items)
    entry_point = str(snapshot.get("entry_point") or "http_endpoint")
    provider = _provider_block(session, snapshot)
    target: dict[str, Any] = {
        "connector": entry_point,
        "endpoint": snapshot.get("url"),
        "method": snapshot.get("method"),
        "provider": provider["name"] if provider is not None else None,
        "provider_kind": provider["kind"] if provider is not None else None,
        # The snapshot's own model wins: a run can name a model the saved
        # provider does not default to.
        "model": snapshot.get("model") or (provider["model"] if provider is not None else None),
    }
    judged = _judge_block(snapshot)

    return {
        "report_version": REPORT_VERSION,
        "project": PROJECT_NAME,
        "run": {
            "id": str(run.id),
            "name": run.name,
            "state": run.state,
            "is_partial": bool(run.is_partial),
            "created_at": _iso(run.created_at),
            "started_at": _iso(run.started_at),
            "completed_at": _iso(run.completed_at),
        },
        "dataset": _dataset_block(session, run),
        "target": target,
        "settings": sanitized_settings(snapshot),
        "permission": _permission_block(snapshot),
        "verdict": {
            "verdict": run.verdict,
            "score": run.score,
            "reason": run.verdict_reason,
            "criteria_profile": run.criteria_profile,
        },
        "metrics": metrics,
        "cases": cases,
        "failed_cases": [case for case in cases if case["state"] == "failed"],
        # A run stopped by the pre-flight keeps its structured setup problem in
        # the snapshot: its remaining cases are "not run", not failed, so the
        # all-failed rule above would miss it.
        "setup_problem": _setup_problem(cases) or _stored_setup_problem(snapshot),
        "safety": _safety_block(metrics),
        "judge": judged,
        "judge_skipped_reason": snapshot.get("judge_skipped_reason"),
        "regression": _regression_block(snapshot),
        "operations": _operations_block(session, run, items, snapshot),
    }


def _operations_block(
    session: Session,
    run: Run,
    items: list[RunItem],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Speed, reliability and token use, with prices from the provider."""
    if run.operations is not None:
        return dict(run.operations)

    price_in: float | None = None
    price_out: float | None = None
    raw_id = snapshot.get("provider_id")
    if isinstance(raw_id, str) and raw_id:
        try:
            provider = session.get(Provider, uuid.UUID(raw_id))
        except ValueError:
            provider = None
        if provider is not None:
            price_in, price_out = prices_from_metadata(provider.provider_config)

    return compute_operations(
        samples_from_items(items),
        price_per_1k_tokens_in=price_in,
        price_per_1k_tokens_out=price_out,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def render_json(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=False, default=str)


def render_csv(document: dict[str, Any]) -> str:
    """Case-level CSV: one row per case, with the run's verdict repeated."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "row_index",
            "input",
            "expected",
            "actual",
            "state",
            "latency_ms",
            "tokens_in",
            "tokens_out",
            "reason",
            "error_kind",
            "http_status",
            "target",
            "error_snippet",
            "verdict",
            "weighted_score",
            # Run-level operations, repeated on every case row so one file has
            # the whole result without a second export.
            "latency_p50_ms",
            "latency_p95_ms",
            "error_rate",
            "timeout_rate",
            "tokens_in_total",
            "tokens_out_total",
            "cost_estimate",
            # Who allowed testing this target, when it was not the user's own app.
            "permission_confirmed",
            "permission_reference",
            "safety_attacks_confirmed",
        ]
    )
    verdict = document["verdict"]
    operations = document.get("operations") or {}
    settings = document.get("settings") or {}
    permission_confirmed = settings.get("permission_confirmed")
    permission_reference = settings.get("permission_reference")
    safety_attacks_confirmed = settings.get("safety_attacks_confirmed")
    for case in document["cases"]:
        writer.writerow(
            [
                csv_cell(case["row_index"]),
                csv_cell(case["input"]),
                csv_cell(case["expected"]),
                csv_cell(case["output"]),
                csv_cell(case["state"]),
                csv_cell(case["latency_ms"]),
                csv_cell(case["tokens_in"]),
                csv_cell(case["tokens_out"]),
                csv_cell(case["reason"]),
                csv_cell(case.get("error_kind")),
                csv_cell(case.get("http_status")),
                csv_cell(case.get("target")),
                csv_cell(case.get("error_snippet")),
                csv_cell(verdict["verdict"]),
                csv_cell("—" if verdict["score"] is None else f"{float(verdict['score']):.2f}"),
                csv_cell(operations.get("latency_p50_ms")),
                csv_cell(operations.get("latency_p95_ms")),
                csv_cell(operations.get("error_rate")),
                csv_cell(operations.get("timeout_rate")),
                csv_cell(operations.get("tokens_in_total")),
                csv_cell(operations.get("tokens_out_total")),
                csv_cell(operations.get("cost_estimate")),
                csv_cell(permission_confirmed),
                csv_cell(permission_reference),
                csv_cell(safety_attacks_confirmed),
            ]
        )
    return buffer.getvalue()


def _format_number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.2f}"


def _esc(value: object) -> str:
    if value is None:
        return "—"
    return html.escape(str(value), quote=True)


def _spaced(value: object) -> str:
    """A snake_case identifier as words, for headings a person reads."""
    return str(value if value is not None else "—").replace("_", " ")


def _ops_number(value: object) -> str:
    """A latency in milliseconds, or an honest dash when nothing was measured."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.0f}"


def _ops_rate(value: object) -> str:
    """A rate as a percentage, or an honest dash when nothing was attempted."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{float(value) * 100:.1f}%"


def _row(cells: list[str]) -> str:
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def render_html(document: dict[str, Any]) -> str:
    """Self-contained, printable HTML: inline CSS only, no external requests."""
    run = document["run"]
    verdict = document["verdict"]
    dataset = document["dataset"]
    target = document["target"]
    safety = document["safety"]
    judge = document["judge"]

    setup = document.get("setup_problem")
    if verdict["score"] is None:
        score = "not measured (no case produced a scored answer)"
    else:
        score = f"{float(verdict['score']):.2f}"

    parts: list[str] = []
    parts.append(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GreenLit report · {_esc(run["name"])}</title>
<style>{_REPORT_STYLE}</style>
</head>
<body>
<p class="brand">Green<span>Lit</span></p>
<h1>Test report · {_esc(run["name"])}</h1>
<p class="muted">{_esc(document["project"])} · run {_esc(run["id"])} · {_esc(run["created_at"])}</p>
"""
    )

    # When nothing could be answered, the first line says so, before any score.
    if setup is not None:
        parts.append(f'<p class="fail" data-testid="setup-problem">{_esc(setup["line"])}</p>')

    # Verdict and the rule that produced it.
    verdict_class = {"GO": "go", "REVIEW": "review", "NO_GO": "no-go"}.get(
        str(verdict["verdict"]), ""
    )
    word = _esc(verdict["verdict"] or "no verdict")
    criteria = _esc(_spaced(verdict["criteria_profile"]))
    state = _esc(run["state"]) + (" · partial" if run["is_partial"] else "")
    parts.append(
        f"""<h2>Verdict</h2>
<div class="verdict">
  <span class="verdict__word {verdict_class}">{word}</span>
  <span>
    <span class="muted">Weighted score</span><br><span class="big">{_esc(score)}</span>
  </span>
  <span><span class="muted">Criteria</span><br>{criteria}</span>
  <span><span class="muted">State</span><br>{state}</span>
</div>
<p>{_esc(verdict["reason"])}</p>
"""
    )

    # The settings snapshot and where the run pointed.
    parts.append("<h2>Test setup</h2><dl>")
    parts.append(f"<dt>Connector</dt><dd>{_esc(target['connector'])}</dd>")
    if target["endpoint"]:
        parts.append(f"<dt>Endpoint</dt><dd>{_esc(target['endpoint'])}</dd>")
    if target["method"]:
        parts.append(f"<dt>Method</dt><dd>{_esc(target['method'])}</dd>")
    parts.append(
        f"<dt>Provider</dt><dd>{_esc(target['provider'] or '—')}</dd>"
        f"<dt>Model</dt><dd>{_esc(target['model'] or '—')}</dd>"
    )
    if dataset is not None:
        name = _esc(dataset["name"])
        version = _esc(dataset["version"])
        parts.append(f"<dt>Dataset</dt><dd>{name} (version {version})</dd>")
        parts.append(f"<dt>Dataset rows</dt><dd>{_esc(dataset['rows'])}</dd>")
        digest = _esc(dataset["content_hash"] or "—")
        parts.append(f"<dt>Dataset hash</dt><dd><code>{digest}</code></dd>")
    parts.append(f"<dt>Started</dt><dd>{_esc(run['started_at'] or '—')}</dd>")
    parts.append(f"<dt>Completed</dt><dd>{_esc(run['completed_at'] or '—')}</dd>")
    permission = document.get("permission")
    if permission is not None:
        parts.append(
            "<dt>Permission to test</dt><dd>confirmed "
            f"({_esc(permission['reference'] or 'no reference given')})</dd>"
        )
        attacks = "on" if permission["safety_attacks_confirmed"] else "off"
        parts.append(f"<dt>Attack probes</dt><dd>{attacks}</dd>")
    parts.append("</dl>")

    parts.append("<h2>Settings snapshot</h2><dl>")
    for key in sorted(document["settings"]):
        value = document["settings"][key]
        if isinstance(value, dict):
            rendered = ", ".join(f"{_esc(name)}: {_esc(entry)}" for name, entry in value.items())
        else:
            rendered = _esc(value)
        parts.append(f"<dt>{_esc(key)}</dt><dd>{rendered}</dd>")
    parts.append("</dl>")

    # Metrics, with "not instrumented" spelled out rather than a 0. One line
    # summarises them so a report never reads like a wall of missing metrics.
    missing = [metric for metric in document["metrics"] if not metric["instrumented"]]
    if missing:
        reasons = list(dict.fromkeys(str(metric["explanation"]) for metric in missing))
        first = reasons[0]
        more = f" and {len(reasons) - 1} more reason(s)" if len(reasons) > 1 else ""
        parts.append(
            f'<p class="muted" data-testid="not-measured">'
            f"{len(missing)} of {len(document['metrics'])} metrics were not measured: "
            f"{_esc(first)}{_esc(more)}.</p>"
        )
    parts.append(
        "<h2>Metrics</h2><table><thead><tr>"
        "<th>Metric</th><th>Score</th><th>State</th><th>Weight</th><th>Why</th>"
        "</tr></thead><tbody>"
    )
    for metric in document["metrics"]:
        if metric["instrumented"]:
            metric_score = f"{float(metric['score']):.2f}"
            css = "pass" if metric["passed"] else "fail"
            state = f'<span class="{css}">{_esc(metric["state"])}</span>'
        else:
            metric_score = "—"
            state = '<span class="skip">not instrumented</span>'
        parts.append(
            _row(
                [
                    _esc(_spaced(metric["name"])),
                    metric_score,
                    state,
                    f"{float(metric['weight']):.2f}",
                    _esc(metric["explanation"]),
                ]
            )
        )
    parts.append("</tbody></table>")

    # Operations: how the app behaved, not how good its answers were.
    operations = document.get("operations") or {}
    parts.append("<h2>Operations</h2><table><thead><tr>")
    parts.append("<th>Measure</th><th>Value</th></tr></thead><tbody>")
    parts.append(_row(["Cases attempted", _esc(operations.get("items_attempted"))]))
    parts.append(_row(["p50 latency (ms)", _ops_number(operations.get("latency_p50_ms"))]))
    parts.append(_row(["p95 latency (ms)", _ops_number(operations.get("latency_p95_ms"))]))
    parts.append(_row(["Error rate", _ops_rate(operations.get("error_rate"))]))
    parts.append(_row(["Timeout rate", _ops_rate(operations.get("timeout_rate"))]))
    parts.append(_row(["Tokens in", _esc(operations.get("tokens_in_total") or "not reported")]))
    parts.append(_row(["Tokens out", _esc(operations.get("tokens_out_total") or "not reported")]))
    if operations.get("cost_configured") and operations.get("cost_estimate") is not None:
        parts.append(_row(["Estimated cost", _esc(operations["cost_estimate"])]))
    else:
        parts.append(_row(["Estimated cost", "not configured"]))
    parts.append("</tbody></table>")

    # Safety, when the run was probed.
    if safety is not None:
        parts.append("<h2>Safety</h2>")
        if not safety["instrumented"]:
            parts.append(f'<p class="muted">{_esc(safety["explanation"])}</p>')
        else:
            parts.append(
                "<table><thead><tr><th>Check</th><th>Result</th><th>Why</th></tr></thead><tbody>"
            )
            parts.append(
                _row(
                    [
                        "Attacks tried",
                        str(safety["attacks_tried"]),
                        "prompt injection, hidden instructions, system-prompt leaks, "
                        "jailbreaks and disallowed requests",
                    ]
                )
            )
            parts.append(
                _row(
                    [
                        "Attacks resisted",
                        f"{safety['attacks_resisted']} of {safety['attacks_tried']}",
                        _esc(safety["explanation"]),
                    ]
                )
            )
            share = (
                "—"
                if safety["over_refusal_share"] is None
                else f"{float(safety['over_refusal_share']):.2f}"
            )
            parts.append(
                _row(
                    [
                        "Over-refusal",
                        share,
                        f"{safety['safe_prompts_refused']} of {safety['safe_prompts']} "
                        "harmless requests were refused",
                    ]
                )
            )
            failures = safety["critical_failures"]
            parts.append(
                _row(
                    [
                        "Critical checks failed",
                        str(len(failures)),
                        (
                            "a leaked secret or a missing refusal is a hard NO-GO: "
                            + _esc(", ".join(failures))
                            if failures
                            else "no critical attack succeeded"
                        ),
                    ]
                )
            )
            parts.append("</tbody></table>")
            if safety["leaked_marker_cases"]:
                parts.append(
                    "<p><strong>The app repeated the planted marker in "
                    f"{_esc(', '.join(safety['leaked_marker_cases']))}.</strong></p>"
                )

    # Judge provenance (spec 8.2).
    parts.append("<h2>Judge</h2>")
    if judge is None:
        skipped = _esc(document["judge_skipped_reason"] or "no judge was configured for this run.")
        parts.append(f'<p class="muted">Judge skipped: {skipped}</p>')
    else:
        parts.append("<dl>")
        parts.append(f"<dt>Judge model</dt><dd>{_esc(judge['model'] or '—')}</dd>")
        parts.append(f"<dt>Rubric version</dt><dd>{_esc(judge['rubric_version'] or '—')}</dd>")
        parts.append(f"<dt>Judge profile</dt><dd>{_esc(judge['profile'] or '—')}</dd>")
        template_hash = _esc(judge["prompt_template_hash"] or "—")
        parts.append(f"<dt>Prompt template hash</dt><dd><code>{template_hash}</code></dd>")
        graded = "—" if judge["graded_items"] is None else str(int(judge["graded_items"]))
        parts.append(f"<dt>Cases graded</dt><dd>{graded}</dd>")
        parts.append("</dl>")

    # Regression against the baseline (spec 8.5).
    parts.append("<h2>Regression</h2>")
    regression = document.get("regression")
    if not isinstance(regression, dict):
        parts.append(
            '<p class="muted">No baseline was set for this dataset version, so there '
            "is nothing to compare.</p>"
        )
    else:
        status = str(regression.get("status") or "")
        status_class = {"PASS": "pass", "WARN": "review", "BLOCK": "fail"}.get(status, "skip")
        parts.append(f'<p class="big {status_class}">{_esc(status)}</p>')
        parts.append(f"<p>{_esc(regression.get('reason'))}</p>")
        baseline_name = _esc(regression.get("baseline_run_name") or "the baseline")
        parts.append(f'<p class="muted">Baseline: {baseline_name}</p>')
        deltas = regression.get("metric_deltas") or []
        if deltas:
            parts.append(
                "<table><thead><tr><th>Metric</th><th>Baseline</th><th>Now</th>"
                "<th>Delta</th></tr></thead><tbody>"
            )
            for delta in deltas:
                change = delta.get("delta")
                parts.append(
                    _row(
                        [
                            _esc(_spaced(delta.get("name"))),
                            _esc(_format_number(delta.get("baseline"))),
                            _esc(_format_number(delta.get("current"))),
                            _esc(f"{change:+.2f}" if isinstance(change, (int, float)) else "—"),
                        ]
                    )
                )
            parts.append("</tbody></table>")
        regressed = regression.get("regressed_cases") or []
        if regressed:
            parts.append(
                f"<p><strong>Cases that passed before and fail now ({len(regressed)}):</strong></p>"
            )
            parts.append("<ul>")
            for case in regressed:
                parts.append(f"<li><pre>{_esc(case.get('input'))}</pre></li>")
            parts.append("</ul>")

    # Failed cases: input, expected, actual, reason.
    parts.append(f"<h2>Cases that failed ({len(document['failed_cases'])})</h2>")
    if not document["failed_cases"]:
        parts.append('<p class="muted">No case failed. Every measured metric passed.</p>')
    else:
        parts.append(
            "<table><thead><tr><th>Input</th><th>Expected</th><th>Actual</th>"
            "<th>Reason</th><th>Target</th><th>Response</th></tr></thead><tbody>"
        )
        for case in document["failed_cases"]:
            status = case.get("http_status")
            where = case.get("target") or "—"
            if status is not None:
                where = f"HTTP {status} · {where}"
            parts.append(
                _row(
                    [
                        f"<pre>{_esc(case['input'])}</pre>",
                        f"<pre>{_esc(case['expected'] or '—')}</pre>",
                        f"<pre>{_esc(case['output'] or '—')}</pre>",
                        _esc(case["reason"] or "—"),
                        _esc(where),
                        f"<pre>{_esc(case.get('error_snippet') or '—')}</pre>",
                    ]
                )
            )
        parts.append("</tbody></table>")

    parts.append(
        "<footer>Generated by GreenLit. This file is self-contained: it needs no network "
        "and no GreenLit install to read.</footer></body></html>"
    )
    return "".join(parts)


def render(document: dict[str, Any], fmt: str) -> tuple[str, str, str]:
    """Return (body, media type, file extension) for one report format."""
    if fmt == "html":
        return render_html(document), "text/html; charset=utf-8", "html"
    if fmt == "json":
        return render_json(document), "application/json", "json"
    if fmt == "csv":
        return render_csv(document), "text/csv; charset=utf-8", "csv"
    raise ValueError(f"Unknown report format {fmt!r}; expected one of {', '.join(FORMATS)}.")
