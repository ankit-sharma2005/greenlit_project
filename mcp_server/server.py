"""GreenLit MCP server: a thin client over the existing REST API.

Read-only tools by default. ``greenlit_start_run`` exists only when
``GREENLIT_MCP_ALLOW_START=1``. Nothing here imports the application, reads its
database or changes a decision rule or threshold: every number comes from the API.

Configuration is environment only: ``GREENLIT_URL`` (default
``http://localhost:8003``), ``GREENLIT_EMAIL`` and ``GREENLIT_PASSWORD``.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import uuid
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_server.client import GreenLitClient, GreenLitError

MAX_PAYLOAD_CHARS = 20_000
MAX_REPORT_CHARS = 100_000
START_COOLDOWN_SECONDS = 10.0
DEFAULT_PROJECT_ID = "default"

ReportFormat = Literal["summary_json", "csv", "html"]
TestType = Literal["quality", "safety", "operations"]

REPORT_FORMATS: dict[str, str] = {"summary_json": "json", "csv": "csv", "html": "html"}
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})

INSTRUCTIONS = (
    "GreenLit decides whether an LLM app is good enough to ship: GO, REVIEW or NO-GO, "
    "with the rule that produced it. These tools read runs, verdicts, reports and the "
    "engine's own criteria from the REST API. They cannot edit settings, delete anything, "
    "create users, change tokens or change a decision rule."
)


def _clip(value: Any, per_string: int) -> Any:
    """Shorten long strings so an oversized payload still fits."""
    if isinstance(value, str):
        return value if len(value) <= per_string else value[:per_string] + "…[truncated]"
    if isinstance(value, dict):
        return {str(key): _clip(item, per_string) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip(item, per_string) for item in value]
    return value


def _bounded(payload: dict[str, Any], limit: int) -> dict[str, Any]:
    """Return the payload, or a clipped version that says it was clipped."""
    size = len(json.dumps(payload, default=str, ensure_ascii=False))
    if size <= limit:
        return {"truncated": False, **payload}
    clipped = _clip(payload, 500)
    clipped_size = len(json.dumps(clipped, default=str, ensure_ascii=False))
    if clipped_size <= limit:
        return {
            "truncated": True,
            "limit_chars": limit,
            "note": "Long text fields were shortened to keep the response small.",
            **clipped,
        }
    head = json.dumps(payload, default=str, ensure_ascii=False)[:limit]
    return {
        "truncated": True,
        "limit_chars": limit,
        "note": "The response was too large to return whole; only its beginning is shown.",
        "head": head,
    }


def _call(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return action()
    except GreenLitError as exc:
        raise ToolError(str(exc)) from None


def _call_text(action: Callable[[], str]) -> str:
    try:
        return action()
    except GreenLitError as exc:
        raise ToolError(str(exc)) from None


def _uuid_arg(value: str, field: str) -> str:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError):
        raise ToolError(
            f"{field} must be a UUID, for example 11111111-1111-4111-8111-111111111111."
        ) from None


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _require_local_target(target: str) -> str:
    """Only targets on this machine may be started from here."""
    cleaned = target.strip()
    parsed = urllib.parse.urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ToolError(
            "target must be a full http(s) URL of an app on this machine, "
            "such as http://localhost:9301/chat."
        )
    host = parsed.hostname.lower()
    if host not in LOCAL_HOSTS and not host.startswith("127."):
        raise ToolError(
            f"Refusing to start a run against {host}: this server starts runs only "
            "against targets on your own machine. Testing somebody else's app needs "
            "the permission record kept with the run, and this server never sets or "
            "changes that record — start that run in the GreenLit UI instead."
        )
    return cleaned


def build_server(
    client: GreenLitClient,
    *,
    allow_start: bool = False,
    now: Callable[[], float] = time.monotonic,
) -> FastMCP:
    """Build the MCP server for one signed-in API client."""
    server = FastMCP(
        name="greenlit",
        instructions=INSTRUCTIONS,
        log_level="WARNING",
    )
    last_start: dict[str, float | None] = {"at": None}

    @server.tool()
    def greenlit_list_projects() -> dict[str, Any]:
        """List the GreenLit project this account can drive, with real counts.

        GreenLit is deployed as one project ("Default project"); the entry is
        built from the signed-in account and the API's own totals, not invented.
        """
        account = _call(lambda: client.get_json("/api/v1/auth/me"))
        datasets = _call(lambda: client.get_json("/api/v1/datasets?limit=1"))
        runs = _call(lambda: client.get_json("/api/v1/runs?limit=1"))
        project = {
            "id": DEFAULT_PROJECT_ID,
            "name": "Default project",
            "implicit": True,
            "account": {
                "name": account.get("name"),
                "email": account.get("email"),
                "role": account.get("role"),
            },
            "dataset_count": _count(datasets.get("total")),
            "run_count": _count(runs.get("total")),
        }
        return _bounded(
            {
                "projects": [project],
                "note": (
                    "GreenLit has a single project per deployment, so this list always "
                    "holds exactly one entry; the counts come from the datasets and runs "
                    "endpoints."
                ),
            },
            MAX_PAYLOAD_CHARS,
        )

    @server.tool()
    def greenlit_get_run_status(run_id: str) -> dict[str, Any]:
        """Progress of one run: its state and how many cases answered, failed,
        were cancelled or have not run yet. Returns no case text or answers."""
        identifier = _uuid_arg(run_id, "run_id")
        run = _call(lambda: client.get_json(f"/api/v1/runs/{identifier}"))
        progress = run.get("progress")
        counters = progress if isinstance(progress, dict) else {}
        total = _count(counters.get("items_total"))
        done = _count(counters.get("items_done"))
        failed = _count(counters.get("items_failed"))
        cancelled = _count(counters.get("items_cancelled"))
        return _bounded(
            {
                "run_id": str(run.get("id", identifier)),
                "name": run.get("name"),
                "state": run.get("state"),
                "stage": counters.get("stage"),
                "is_partial": bool(run.get("is_partial")),
                "counts": {
                    "total": total,
                    "answered": max(0, done - failed - cancelled),
                    "failed": failed,
                    "cancelled": cancelled,
                    "not_run": max(0, total - done),
                },
                "started_at": run.get("started_at"),
                "completed_at": run.get("completed_at"),
            },
            MAX_PAYLOAD_CHARS,
        )

    @server.tool()
    def greenlit_get_verdict(run_id: str) -> dict[str, Any]:
        """The result of a finished run: GO / REVIEW / NO-GO, the weighted score,
        the API's own plain-language reason, and the instrumented metrics that failed."""
        identifier = _uuid_arg(run_id, "run_id")
        run = _call(lambda: client.get_json(f"/api/v1/runs/{identifier}"))
        metrics = run.get("metrics")
        rows = metrics if isinstance(metrics, list) else []
        failed_metrics = [
            {
                "name": row.get("name"),
                "score": row.get("score"),
                "threshold": row.get("threshold"),
            }
            for row in rows
            if isinstance(row, dict)
            and row.get("instrumented") is True
            and row.get("passed") is False
        ]
        return _bounded(
            {
                "run_id": str(run.get("id", identifier)),
                "state": run.get("state"),
                "verdict": run.get("verdict"),
                "weighted_score": run.get("score"),
                "headline": run.get("verdict_reason"),
                "reasons": None,
                "reasons_note": (
                    "The API returns one plain-language reason (verdict_reason) and no "
                    "separate reasons list, so the headline above is the whole explanation."
                ),
                "failed_metrics": failed_metrics,
            },
            MAX_PAYLOAD_CHARS,
        )

    @server.tool()
    def greenlit_get_report(
        run_id: str,
        format: ReportFormat = "summary_json",
    ) -> dict[str, Any]:
        """Export a run's report. summary_json is the report document as JSON, csv is
        case-level rows, html is the printable report. Long reports are truncated."""
        identifier = _uuid_arg(run_id, "run_id")
        api_format = REPORT_FORMATS[format]
        text = _call_text(
            lambda: client.get_text(f"/api/v1/runs/{identifier}/report?format={api_format}")
        )
        truncated = len(text) > MAX_REPORT_CHARS
        result: dict[str, Any] = {
            "truncated": truncated,
            "format": format,
            "limit_chars": MAX_REPORT_CHARS,
            "content": text[:MAX_REPORT_CHARS],
            "original_chars": len(text),
        }
        if truncated:
            result["note"] = (
                f"The report was {len(text)} characters; only the first "
                f"{MAX_REPORT_CHARS} are returned."
            )
        return result

    @server.tool()
    def greenlit_get_criteria() -> dict[str, Any]:
        """The engine's own criteria: metric weights, thresholds, hard gates and
        the decision rules in the order they run, exactly as the API reports them."""
        overview = _call(lambda: client.get_json("/api/v1/criteria"))
        return _bounded(overview, MAX_PAYLOAD_CHARS)

    if allow_start:

        @server.tool()
        def greenlit_start_run(
            project_id: str,
            dataset_id: str,
            target: str,
            test_types: list[TestType] | None = None,
        ) -> dict[str, Any]:
            """Start a run and return its id immediately; poll
            greenlit_get_run_status for progress. Only local targets are accepted,
            and at most one start every 10 seconds. Enabled by the operator through
            GREENLIT_MCP_ALLOW_START=1."""
            if project_id != DEFAULT_PROJECT_ID:
                raise ToolError(
                    f"Unknown project {project_id!r}: GreenLit has one project, "
                    f"{DEFAULT_PROJECT_ID!r} (see greenlit_list_projects)."
                )
            dataset = _uuid_arg(dataset_id, "dataset_id")
            url = _require_local_target(target)
            kinds = list(test_types) if test_types else ["quality"]
            moment = now()
            previous = last_start["at"]
            if previous is not None and moment - previous < START_COOLDOWN_SECONDS:
                wait = START_COOLDOWN_SECONDS - (moment - previous)
                raise ToolError(
                    f"One start every {int(START_COOLDOWN_SECONDS)} seconds; "
                    f"try again in {wait:.1f}s."
                )
            last_start["at"] = moment
            created = _call(
                lambda: client.post_json(
                    "/api/v1/runs",
                    {
                        "entry_point": "http_endpoint",
                        "target": url,
                        "dataset_id": dataset,
                        "test_types": kinds,
                        "allow_private_targets": True,
                    },
                )
            )
            run = created.get("run")
            record = run if isinstance(run, dict) else created
            return {
                "truncated": False,
                "run_id": record.get("id"),
                "state": record.get("state"),
                "project_id": project_id,
                "dataset_id": dataset,
                "target": url,
                "test_types": kinds,
                "next_step": "Poll greenlit_get_run_status with this run_id.",
            }

    return server
