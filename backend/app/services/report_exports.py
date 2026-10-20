from __future__ import annotations

import csv
import html
import io
import json
import textwrap
import unicodedata

from app.phase5_schemas import RunReportItem, RunReportOut


def render_html_report(report: RunReportOut) -> str:
    metadata = report.metadata
    metric_rows = "".join(
        "<tr>"
        f"<td>{_escape(metric.name)}</td>"
        f"<td>{_escape(metric.category)}</td>"
        f"<td>{_score_text(metric.mean_score)}</td>"
        f"<td>{metric.scored_cases}</td>"
        f"<td>{_score_text(metric.hard_gate_threshold)}</td>"
        f"<td>{metric.hard_gate_failures}</td>"
        "</tr>"
        for metric in report.metrics
    )
    case_sections = "".join(_case_html(item) for item in report.items)
    failed_cases = (
        "".join(_case_html(item) for item in report.failed_cases)
        or "<p>No failed cases.</p>"
    )
    settings = _escape(_json_text(metadata.settings))
    criteria = _escape(_json_text(report.rules_applied.model_dump(mode="json")))
    safety = _escape(_json_text(report.safety_results))
    regression = _escape(_json_text(report.regression_vs_baseline))
    calibration = _escape(_json_text(report.calibration_summary))
    reasons = (
        "".join(f"<li>{_escape(reason)}</li>" for reason in report.verdict.reasons)
        or "<li>No reasons recorded.</li>"
    )
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>GreenLit evaluation report - {_escape(report.run_id)}</title>",
        "<style>",
        "body { font: 15px/1.5 system-ui,sans-serif; color: #17212b; "
        "max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }",
        "h1,h2 { line-height: 1.2; } table { border-collapse: collapse; "
        "width: 100%; margin: 1rem 0 2rem; }",
        "th,td { border: 1px solid #ccd4dc; padding: .45rem; text-align: left; "
        "vertical-align: top; }",
        "th { background: #eef2f6; } pre { white-space: pre-wrap; "
        "overflow-wrap: anywhere; background: #f5f7fa; padding: 1rem; }",
        ".verdict { font-size: 1.25rem; font-weight: 700; } "
        ".case { border-top: 1px solid #ccd4dc; padding: 1rem 0; }",
        "@media print { body { max-width: none; margin: 0; padding: 0; } "
        "section { break-inside: avoid; } }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>GreenLit evaluation report</h1>",
        '<p class="verdict">'
        f"{_escape(report.verdict.verdict)} · {_escape(report.verdict.summary)}</p>",
        "<h2>Run and application</h2>",
        "<table><tbody>",
        f"<tr><th>Project</th><td>{_escape(metadata.project_name)}</td></tr>",
        "<tr><th>Dataset</th><td>"
        f"{_escape(metadata.dataset_name)} v{metadata.dataset_version} · "
        f"{_escape(metadata.dataset_hash)}</td></tr>",
        "<tr><th>Connector</th><td>"
        f"{_escape(metadata.connector_type or 'Not recorded')}</td></tr>",
        "<tr><th>Provider / model</th><td>"
        f"{_escape(metadata.provider_name or 'Not recorded')} / "
        f"{_escape(metadata.model or 'Not recorded')}</td></tr>",
        f"<tr><th>Run ID</th><td>{_escape(report.run_id)}</td></tr>",
        f"<tr><th>Created</th><td>{_escape(metadata.run_created_at)}</td></tr>",
        "<tr><th>App version</th>"
        f"<td>{metadata.app_version} · {_escape(metadata.app_version_id)}</td></tr>",
        "<tr><th>Status / score</th>"
        f"<td>{_escape(report.status)} / {_score_text(report.verdict.score)}</td></tr>",
        "</tbody></table>",
        f"<h2>Settings</h2><pre>{settings}</pre>",
        f"<h2>Rules applied</h2><pre>{criteria}</pre>",
        "<h2>Metric results and hard-gate thresholds</h2>",
        "<table><thead><tr><th>Metric</th><th>Category</th><th>Mean score</th>"
        "<th>Scored cases</th><th>Hard-gate threshold</th><th>Gate failures</th>"
        f"</tr></thead><tbody>{metric_rows}</tbody></table>",
        f"<h2>Verdict reasons</h2><ul>{reasons}</ul>",
        f"<h2>Failed cases</h2>{failed_cases}",
        f"<h2>Safety results</h2><pre>{safety}</pre>",
        f"<h2>Regression vs baseline</h2><pre>{regression}</pre>",
        f"<h2>Calibration summary</h2><pre>{calibration}</pre>",
        f"<h2>All cases</h2>{case_sections or '<p>No case results recorded.</p>'}",
        "</body>",
        "</html>",
    ]
    return "\n".join(parts)


def render_case_csv(report: RunReportOut) -> str:
    buffer = io.StringIO(newline="")
    fields = [
        "run_id",
        "run_status",
        "project_id",
        "project",
        "dataset_id",
        "dataset",
        "dataset_version",
        "dataset_hash",
        "connector_type",
        "provider",
        "model",
        "app_version_id",
        "app_version",
        "run_created_at",
        "run_started_at",
        "run_finished_at",
        "verdict",
        "overall_score",
        "rules_applied",
        "settings",
        "verdict_reasons",
        "metric_summary",
        "failed_case",
        "case_position",
        "dataset_item_id",
        "case_status",
        "category",
        "input",
        "reference_answer",
        "output",
        "error",
        "metric",
        "metric_category",
        "metric_method",
        "metric_status",
        "score",
        "hard_gate_threshold",
        "hard_gate_failure",
        "reason",
        "safety_results",
        "regression_vs_baseline",
        "calibration_summary",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    metadata = report.metadata
    metrics_by_name = {metric.name: metric for metric in report.metrics}
    failed_case_ids = {item.id for item in report.failed_cases}
    common = {
        "run_id": report.run_id,
        "run_status": report.status,
        "project_id": metadata.project_id,
        "project": metadata.project_name,
        "dataset_id": metadata.dataset_id,
        "dataset": metadata.dataset_name,
        "dataset_version": metadata.dataset_version,
        "dataset_hash": metadata.dataset_hash,
        "connector_type": metadata.connector_type,
        "provider": metadata.provider_name,
        "model": metadata.model,
        "app_version_id": metadata.app_version_id,
        "app_version": metadata.app_version,
        "run_created_at": metadata.run_created_at,
        "run_started_at": metadata.run_started_at,
        "run_finished_at": metadata.run_finished_at,
        "verdict": report.verdict.verdict,
        "overall_score": report.verdict.score,
        "rules_applied": _json_text(report.rules_applied.model_dump(mode="json")),
        "settings": _json_text(metadata.settings),
        "verdict_reasons": _json_text(report.verdict.reasons),
        "metric_summary": _json_text(
            [metric.model_dump(mode="json") for metric in report.metrics]
        ),
        "safety_results": _json_text(report.safety_results),
        "regression_vs_baseline": _json_text(report.regression_vs_baseline),
        "calibration_summary": _json_text(report.calibration_summary),
    }
    for item in report.items:
        base = {
            **common,
            "case_position": item.position,
            "dataset_item_id": item.dataset_item_id,
            "case_status": item.status,
            "failed_case": item.id in failed_case_ids,
            "category": item.category,
            "input": item.input,
            "reference_answer": item.reference_answer,
            "output": item.output,
            "error": item.error,
        }
        if not item.scores:
            writer.writerow(_safe_csv_row(base))
            continue
        for score in item.scores:
            metric = metrics_by_name.get(score.name)
            gate = metric.hard_gate_threshold if metric else None
            writer.writerow(
                _safe_csv_row(
                    {
                        **base,
                        "metric": score.name,
                        "metric_category": score.category,
                        "metric_method": score.method,
                        "metric_status": score.status,
                        "score": score.score,
                        "hard_gate_threshold": gate,
                        "hard_gate_failure": (
                            gate is not None
                            and score.score is not None
                            and score.score < gate
                        ),
                        "reason": score.reason,
                    }
                )
            )
    return buffer.getvalue()


def render_pdf_report(report: RunReportOut) -> bytes:
    lines = _report_text_lines(report)
    wrapped = [
        segment
        for line in lines
        for segment in textwrap.wrap(
            _pdf_text(line),
            width=100,
            break_long_words=True,
            break_on_hyphens=False,
        )
    ]
    page_lines = [wrapped[index : index + 56] for index in range(0, len(wrapped), 56)]
    if not page_lines:
        page_lines = [["GreenLit evaluation report"]]
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # Filled with the page tree after page IDs are known.
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    page_ids: list[int] = []
    for page_number, content_lines in enumerate(page_lines):
        page_id = 4 + page_number * 2
        content_id = page_id + 1
        page_ids.append(page_id)
        text_commands = [
            "BT",
            "/F1 9 Tf",
            "42 750 Td",
            "12 TL",
        ]
        for line in content_lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            text_commands.extend([f"({escaped}) Tj", "T*"])
        text_commands.append("ET")
        stream = ("\n".join(text_commands) + "\n").encode("ascii")
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        content = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"endstream"
        )
        objects.extend([page, content])
    objects[1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] "
        f"/Count {len(page_ids)} >>"
    ).encode("ascii")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _case_html(case: RunReportItem) -> str:
    score_rows = "".join(
        "<tr>"
        f"<td>{_escape(score.name)}</td>"
        f"<td>{_escape(score.status)}</td>"
        f"<td>{_score_text(score.score)}</td>"
        f"<td>{_escape(score.reason)}</td>"
        "</tr>"
        for score in case.scores
    )
    return (
        '<article class="case">'
        f"<h3>Case #{case.position} · {_escape(case.status)} · "
        f"{_escape(case.category)}</h3>"
        f"<p><strong>Input:</strong> {_escape(case.input)}</p>"
        "<p><strong>Reference:</strong> "
        f"{_escape(case.reference_answer or 'Not provided')}</p>"
        f"<p><strong>Output:</strong> {_escape(case.output or 'No output')}</p>"
        f"<p><strong>Error:</strong> {_escape(case.error or 'None')}</p>"
        "<table><thead><tr><th>Metric</th><th>Status</th><th>Score</th>"
        "<th>Reason</th></tr></thead>"
        f"<tbody>{score_rows}</tbody></table></article>"
    )


def _report_text_lines(report: RunReportOut) -> list[str]:
    metadata = report.metadata
    lines = [
        "GreenLit evaluation report",
        f"Project: {metadata.project_name}",
        (
            f"Dataset: {metadata.dataset_name} v{metadata.dataset_version} "
            f"(hash {metadata.dataset_hash})"
        ),
        f"Connector: {metadata.connector_type or 'Not recorded'}",
        (
            f"Provider/model: {metadata.provider_name or 'Not recorded'} / "
            f"{metadata.model or 'Not recorded'}"
        ),
        f"Run ID: {report.run_id}",
        f"Created: {metadata.run_created_at}",
        f"Started: {metadata.run_started_at or 'Not recorded'}",
        f"Finished: {metadata.run_finished_at or 'Not recorded'}",
        f"App version: {metadata.app_version} ({metadata.app_version_id})",
        (
            f"Verdict: {report.verdict.verdict}; "
            f"score: {_score_text(report.verdict.score)}"
        ),
        f"Summary: {report.verdict.summary}",
        "",
        "Settings:",
        _json_text(metadata.settings),
        "Rules applied:",
        _json_text(report.rules_applied.model_dump(mode="json")),
        "Metric results:",
    ]
    for metric in report.metrics:
        lines.append(
            f"- {metric.name} ({metric.category}): "
            f"mean={_score_text(metric.mean_score)}, "
            f"cases={metric.scored_cases}, "
            f"hard gate={_score_text(metric.hard_gate_threshold)}, "
            f"failures={metric.hard_gate_failures}"
        )
    lines.extend(
        ["", "Verdict reasons:", *[f"- {reason}" for reason in report.verdict.reasons]]
    )
    lines.append("Failed cases:")
    for item in report.failed_cases:
        lines.append(
            f"- Case #{item.position} [{item.status}/{item.category}] "
            f"input={item.input}; output={item.output or 'No output'}; "
            f"error={item.error or 'None'}"
        )
    lines.extend(
        [
            "",
            "Safety results:",
            _json_text(report.safety_results),
            "Regression vs baseline:",
            _json_text(report.regression_vs_baseline),
            "Calibration summary:",
            _json_text(report.calibration_summary),
            "All cases:",
        ]
    )
    for item in report.items:
        lines.append(
            f"Case #{item.position} ({item.status}, {item.category}) "
            f"input={item.input}; output={item.output or 'No output'}"
        )
        for score in item.scores:
            lines.append(
                f"  {score.name}: {_score_text(score.score)} [{score.status}] "
                f"{score.reason}"
            )
    return lines


def _safe_csv_row(row: dict[str, object]) -> dict[str, object]:
    return {key: _safe_csv_cell(value) for key, value in row.items()}


def _safe_csv_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _score_text(value: float | None) -> str:
    return "Not scored" if value is None else f"{value:.3f}"


def _pdf_text(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", value).encode("ascii", "replace").decode("ascii")
    )


def sanitize_report_mapping(value: dict[str, object]) -> dict[str, object]:
    return {
        key: _sanitize_report_value(item)
        for key, item in value.items()
        if not _is_sensitive_report_key(key)
    }


def _sanitize_report_value(value: object) -> object:
    if isinstance(value, dict):
        return sanitize_report_mapping(value)
    if isinstance(value, list):
        return [_sanitize_report_value(item) for item in value]
    return value


def _is_sensitive_report_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    sensitive_fragments = (
        "secret",
        "password",
        "credential",
        "authorization",
        "api_key",
        "private_key",
    )
    sensitive_names = {
        "token",
        "api_token",
        "access_token",
        "refresh_token",
        "bearer_token",
    }
    return normalized in sensitive_names or any(
        fragment in normalized for fragment in sensitive_fragments
    )
