"""The five local demo apps GreenLit can show, connect and test.

Everything here is compiled into the backend: the addresses, the connector shape
and the start commands. A request never supplies an address, so the status check
cannot be turned into a port scanner or an SSRF probe — it may only ``GET /health``
on the five fixed URLs below, with a short timeout and no redirects, and it
reports nothing but up/down plus the app's own ``app``/``mode``/``provider``/
``model`` strings.

These apps are weak by design (no auth, no TLS) and must stay on this machine.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

HEALTH_TIMEOUT_SECONDS = 2.0
HEALTH_FIELDS = ("app", "mode", "provider", "model")

WARNING = (
    "This is a local demo app: it has no authentication and is weak by design. "
    "It is reachable only from this computer and must never be exposed to the internet."
)


@dataclass(frozen=True)
class DemoMode:
    """One mode the app can run in, and what it is for."""

    mode: str
    shows: str


@dataclass(frozen=True)
class DemoApp:
    """One catalog entry: where it lives and exactly what to put in GreenLit."""

    id: str
    name: str
    description: str
    entry_point: str
    url: str
    method: str
    response_format: str
    answer_path: str | None
    context_path: str | None
    body_template: str | None
    timeout_seconds: int
    mcp_tool: str | None
    start_bash: str
    start_windows: str
    modes: tuple[DemoMode, ...] = field(default_factory=tuple)


CATALOG: tuple[DemoApp, ...] = (
    DemoApp(
        id="support-bot",
        name="Acme support bot",
        description=("A support persona with a fixed FAQ in its system prompt; one JSON answer."),
        entry_point="http_endpoint",
        url="http://host.docker.internal:9111/",
        method="POST",
        response_format="json",
        answer_path="$.answer",
        context_path=None,
        body_template='{"question": "{{question}}"}',
        timeout_seconds=150,
        mcp_tool=None,
        start_bash="cd experiments/llm_apps && python support_bot/app.py",
        start_windows="cd experiments\\llm_apps; python support_bot\\app.py",
        modes=(
            DemoMode("guarded", "the reviewed prompt with its safety rules"),
            DemoMode("weak", "no safety rules, with a planted synthetic note"),
        ),
    ),
    DemoApp(
        id="docs-rag",
        name="Acme docs RAG",
        description=(
            "Retrieval over nine short documents; the top passages are returned as context."
        ),
        entry_point="http_endpoint",
        url="http://host.docker.internal:9112/",
        method="POST",
        response_format="json",
        answer_path="$.answer",
        context_path="$.context",
        body_template='{"question": "{{question}}"}',
        timeout_seconds=150,
        mcp_tool=None,
        start_bash="cd experiments/llm_apps && python docs_rag/app.py",
        start_windows="cd experiments\\llm_apps; python docs_rag\\app.py",
        modes=(
            DemoMode("normal", "retrieves the passages that contain the answer"),
            DemoMode("wrong_docs", "retrieves seeded irrelevant passages"),
        ),
    ),
    DemoApp(
        id="stream-bot",
        name="Acme streaming bot",
        description="The same persona over SSE, NDJSON, plain text and one JSON body.",
        entry_point="http_endpoint",
        url="http://host.docker.internal:9113/sse",
        method="POST",
        response_format="sse",
        answer_path="delta",
        context_path=None,
        body_template='{"question": "{{question}}"}',
        timeout_seconds=150,
        mcp_tool=None,
        start_bash="cd experiments/llm_apps && python stream_bot/app.py",
        start_windows="cd experiments\\llm_apps; python stream_bot\\app.py",
        modes=(
            DemoMode("guarded", "the same answer on /sse, /ndjson, /text and /"),
            DemoMode("weak", "no safety rules, with a planted synthetic note"),
        ),
    ),
    DemoApp(
        id="tool-agent",
        name="Acme tool agent",
        description="An MCP server over Streamable HTTP with a calculator and an order lookup.",
        entry_point="mcp",
        url="http://host.docker.internal:9114/mcp",
        method="POST",
        response_format="json",
        answer_path=None,
        context_path=None,
        body_template=None,
        timeout_seconds=150,
        mcp_tool="ask_assistant",
        start_bash="cd experiments/llm_apps && .venv/bin/python tool_agent/server.py",
        start_windows="cd experiments\\llm_apps; .venv\\Scripts\\python.exe tool_agent\\server.py",
        modes=(
            DemoMode("ask_assistant", "one model-backed answer through the tool"),
            DemoMode("calculator", "a deterministic arithmetic tool, no model"),
        ),
    ),
    DemoApp(
        id="math-solver",
        name="Acme math solver",
        description=(
            "Deterministic arithmetic with no model; a seeded 30 % of questions are "
            "wrong in faulty_30."
        ),
        entry_point="http_endpoint",
        url="http://host.docker.internal:9115/",
        method="POST",
        response_format="json",
        answer_path="$.answer",
        context_path=None,
        body_template='{"question": "{{question}}"}',
        timeout_seconds=30,
        mcp_tool=None,
        start_bash=("cd experiments/llm_apps && DEMO_CONTROL=1 python math_solver/app.py"),
        start_windows=(
            'cd experiments\\llm_apps; $env:DEMO_CONTROL="1"; python math_solver\\app.py'
        ),
        modes=(
            DemoMode("correct", "every arithmetic answer is right, the same every run"),
            DemoMode("faulty_30", "the same seeded 30 % of questions answer wrongly"),
        ),
    ),
)

_BY_ID = {entry.id: entry for entry in CATALOG}


def get_entry(app_id: str) -> DemoApp | None:
    """The catalog entry with this id, or None (the API answers 404)."""
    return _BY_ID.get(app_id)


def app_dict(entry: DemoApp) -> dict[str, Any]:
    """Everything the Settings card and the connector need, without a probe."""
    return {
        "id": entry.id,
        "name": entry.name,
        "description": entry.description,
        "entry_point": entry.entry_point,
        "url": entry.url,
        "method": entry.method,
        "response_format": entry.response_format,
        "answer_path": entry.answer_path,
        "context_path": entry.context_path,
        "body_template": entry.body_template,
        "timeout_seconds": entry.timeout_seconds,
        "mcp_tool": entry.mcp_tool,
        "start_bash": entry.start_bash,
        "start_windows": entry.start_windows,
        "modes": [{"mode": item.mode, "shows": item.shows} for item in entry.modes],
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is not followed: the probe answers about this address only."""

    def redirect_request(
        self, req: Any, fp: Any, code: Any, msg: Any, headers: Any, newurl: Any
    ) -> None:
        return None


E2E_FLAG_ENV = "GREENLIT_E2E"
ORIGINS_ENV = "DEMO_CATALOG_PROBE_ORIGINS"


def read_probe_origins(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The test-only probe origins, read once from the process environment.

    This exists because the e2e stack cannot reach the real catalog ports. It is
    honoured only when ``GREENLIT_E2E=1`` is also set; without that flag it is
    ignored with one warning. It can only replace the scheme, host and port of a
    *known* catalog entry — never add an address, never add an id — and it is
    never read from a request, a header, a query string or the database.
    """
    source = os.environ if env is None else env
    raw = (source.get(ORIGINS_ENV) or "").strip()
    if not raw:
        return {}
    if (source.get(E2E_FLAG_ENV) or "").strip() != "1":
        logger.warning("%s is ignored: it only works when %s=1", ORIGINS_ENV, E2E_FLAG_ENV)
        return {}
    origins: dict[str, str] = {}
    known = {entry.id for entry in CATALOG}
    for pair in raw.split(","):
        app_id, separator, origin = pair.partition("=")
        app_id = app_id.strip()
        origin = origin.strip()
        if not separator or app_id not in known:
            logger.warning("%s: ignoring unknown entry %r", ORIGINS_ENV, app_id)
            continue
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            logger.warning("%s: ignoring %r for %s", ORIGINS_ENV, origin, app_id)
            continue
        # Scheme, host and port only: the catalog's own path is kept.
        origins[app_id] = f"{parsed.scheme}://{parsed.netloc}"
    return origins


# Read once at import, which is the process start for the API worker.
PROBE_ORIGINS: dict[str, str] = read_probe_origins()


def probe_url(entry: DemoApp) -> str:
    """The /health URL for one entry: the catalog's, or its e2e override's origin."""
    url = entry.url.split("?", 1)[0]
    override = PROBE_ORIGINS.get(entry.id)
    if override:
        parsed = urllib.parse.urlsplit(url)
        path = parsed.path or "/"
        url = override + path
    return url if url.endswith("/health") else url.rstrip("/") + "/health"


def probe_health(entry: DemoApp) -> dict[str, str]:
    """GET the entry's own /health and keep only the four known strings.

    The URL comes from the catalog argument, never from a request, and the
    timeout is short so a dead app cannot hold the page.
    """
    url = probe_url(entry)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return {"state": "down"}
            body = json.loads(response.read(4096))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return {"state": "down"}
    if not isinstance(body, dict) or body.get("status") != "ok":
        return {"state": "down"}
    status = {"state": "up"}
    for name in HEALTH_FIELDS:
        value = body.get(name)
        if isinstance(value, str):
            status[name] = value[:80]
    return status


def statuses() -> list[dict[str, Any]]:
    """The catalog with one probe each, in catalog order."""
    items: list[dict[str, Any]] = []
    for entry in CATALOG:
        items.append({**app_dict(entry), "status": probe_health(entry)})
    return items
