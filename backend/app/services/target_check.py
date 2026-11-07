"""The "Check before full run" step (STEP 2).

A first real test against somebody else's app is where a wrong answer path or a
missing session cookie costs a whole run. This module sends exactly one
harmless request with the run's own connector settings, shows what GreenLit
would read back, and remembers that a person accepted that reading — bound to a
fingerprint of the target settings, so a changed URL, template or mapping needs
a fresh check. Nothing here creates a run or stores an answer.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, DatasetColumnMapping, DatasetItem, DatasetVersion, User
from app.services.connectors import ConnectorError, Trace, render_body_template
from app.services.target_error import error_detail, target_of
from app.services.target_error import redact_snippet as _redact

CHECK_TTL_SECONDS = 30 * 60
MAX_ANSWER_CHARS = 500
MAX_CANDIDATE_PREVIEW = 120
MAX_CANDIDATES = 10
_CANDIDATE_DEPTH = 6
# Sent when no dataset case can supply a question; harmless by construction.
HARMLESS_INPUT = "Hello"
MASK = "XXXX"


class TargetCheckError(ValueError):
    """A check that cannot be honoured; ``status`` maps to the HTTP code."""

    def __init__(
        self, message: str, *, status: int = 422, code: str = "target_check_error"
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


@dataclass
class TargetCheck:
    """One stored check: who made it, what it was bound to, and its result."""

    id: str
    owner_id: str
    config_hash: str
    result: dict[str, Any]
    created_at: float
    expires_at: float
    accepted: bool = False
    accepted_at: float | None = None


# Checks live in the API process for at most 30 minutes: they are a confirmation
# step, not a record. A restart only means "run the check again".
_CHECKS: dict[str, TargetCheck] = {}
_LOCK = threading.Lock()


def _now() -> float:
    return time.time()


def clear_checks() -> None:
    """Drop every stored check (tests, and a restart in effect)."""
    with _LOCK:
        _CHECKS.clear()


def _header_names(snapshot: Mapping[str, Any]) -> list[str]:
    """The header names a check is bound to; values are never read here."""
    raw = snapshot.get("header_names")
    if isinstance(raw, list) and raw:
        return sorted({str(name) for name in raw})
    return sorted({str(name) for name in dict(snapshot.get("headers") or {})})


def fingerprint(snapshot: Mapping[str, Any]) -> str:
    """A stable hash of the target settings a check and a run must share."""
    payload = {
        "url": str(snapshot.get("url") or "").strip(),
        "method": str(snapshot.get("method") or "POST").upper(),
        "header_names": _header_names(snapshot),
        "body_template": str(snapshot.get("body_template") or ""),
        "answer_path": str(snapshot.get("answer_path") or ""),
        "context_path": str(snapshot.get("context_path") or ""),
        "response_format": str(snapshot.get("response_format") or "json"),
        "stream_content_path": str(snapshot.get("stream_content_path") or ""),
        # An MCP target's call is a different request when the tool, the question
        # argument or the static arguments change, so the check is bound to them.
        "mcp_tool": str(snapshot.get("mcp_tool") or ""),
        "mcp_question_arg": str(snapshot.get("mcp_question_arg") or ""),
        "mcp_extra_args": snapshot.get("mcp_extra_args") or {},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _redacted_url(url: str) -> str:
    """The URL a person may see: query values masked, no userinfo, no fragment."""
    from urllib.parse import urlsplit, urlunsplit

    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return MASK
    netloc = parts.netloc
    if "@" in netloc:
        netloc = f"{MASK}@{netloc.rsplit('@', 1)[-1]}"
    query = ""
    if parts.query:
        pairs = []
        for pair in parts.query.split("&"):
            key = pair.split("=", 1)[0]
            pairs.append(f"{key}={MASK}" if key else MASK)
        query = "&".join(pairs)
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def _redacted_request(snapshot: Mapping[str, Any], input_text: str) -> dict[str, Any]:
    """Exactly what will be sent, with every secret replaced by XXXX."""
    headers = _header_names(snapshot)
    if str(snapshot.get("entry_point") or "") == "mcp_server":
        # An MCP call is a tool name plus arguments; the static arguments are
        # masked like header values because a person may have put a token there.
        extra = snapshot.get("mcp_extra_args")
        arguments = dict.fromkeys(sorted(extra), MASK) if isinstance(extra, dict) else {}
        question_arg = str(snapshot.get("mcp_question_arg") or "")
        if question_arg:
            arguments[question_arg] = input_text
        return {
            "method": "MCP tools/call",
            "url": _redacted_url(str(snapshot.get("url") or "")),
            "headers": dict.fromkeys(headers, MASK),
            "tool": str(snapshot.get("mcp_tool") or ""),
            "arguments": arguments,
            "input": input_text,
        }
    template = str(snapshot.get("body_template") or '{"question": {{input}}}')
    return {
        "method": str(snapshot.get("method") or "POST").upper(),
        "url": _redacted_url(str(snapshot.get("url") or "")),
        "headers": dict.fromkeys(headers, MASK),
        "body": render_body_template(template, input_text),
        "input": input_text,
    }


def _looks_like_html(answer: str) -> bool:
    head = answer.lstrip()[:200].lower()
    return head.startswith("<") or "<html" in head or "<!doctype" in head


def extraction_hint(answer: str, answer_path: str | None) -> str | None:
    """Plain words for the two ways a first check usually reads wrong."""
    if not answer.strip():
        return (
            "GreenLit found no answer text in the response. Check the answer path (the JSON "
            "key that holds the reply), the session cookie, and that the URL is the app's "
            "message endpoint rather than its home page."
        )
    if _looks_like_html(answer):
        return (
            "The answer looks like an HTML page, not a reply. The app may be showing a login "
            "or error page: check the answer path (or the URL), and paste a fresh cURL if the "
            "session expired."
        )
    if not answer_path:
        return (
            "No answer path is set, so GreenLit recognised this by shape alone. If the text "
            "above is not the app's reply, set the answer path and check again."
        )
    return None


def _status_from(error: ConnectorError) -> int | None:
    raw = (error.details or {}).get("status_code")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def first_case_input(
    session: Session, user: User, dataset_version_id: uuid.UUID | None
) -> tuple[str, str | None]:
    """The first case of the approved dataset, or a fixed harmless input.

    Returns the text to send and the dataset row's input column name, so the
    check asks the app the same kind of question a run will.
    """
    if dataset_version_id is None:
        return HARMLESS_INPUT, None
    version = session.get(DatasetVersion, dataset_version_id)
    if version is None or version.approved_at is None:
        return HARMLESS_INPUT, None
    dataset = session.get(Dataset, version.dataset_id)
    if dataset is None or dataset.owner_id != user.id:
        return HARMLESS_INPUT, None
    mapping = session.scalar(
        select(DatasetColumnMapping).where(DatasetColumnMapping.dataset_id == dataset.id)
    )
    column = mapping.input_column if mapping is not None else "question"
    item = session.scalar(
        select(DatasetItem)
        .where(DatasetItem.dataset_version_id == version.id)
        .order_by(DatasetItem.row_index)
    )
    if item is None:
        return HARMLESS_INPUT, column
    data = item.data if isinstance(item.data, dict) else {}
    for key in (column, f"{column}_text", "question", "input", "prompt"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), column
    return HARMLESS_INPUT, column


def record_check(
    *,
    owner_id: uuid.UUID,
    config_hash: str,
    result: dict[str, Any],
) -> TargetCheck:
    """Store one check result under a fresh id."""
    now = _now()
    check = TargetCheck(
        id=str(uuid.uuid4()),
        owner_id=str(owner_id),
        config_hash=config_hash,
        result=result,
        created_at=now,
        expires_at=now + CHECK_TTL_SECONDS,
    )
    with _LOCK:
        _CHECKS[check.id] = check
    return check


def get_check(check_id: str, owner_id: uuid.UUID) -> TargetCheck | None:
    with _LOCK:
        check = _CHECKS.get(check_id)
    if check is None or check.owner_id != str(owner_id):
        return None
    return check


def accept_check(check_id: str, owner_id: uuid.UUID) -> TargetCheck:
    """The person confirmed the extraction; this is what unlocks a full run."""
    check = get_check(check_id, owner_id)
    if check is None:
        raise TargetCheckError(
            "That check was not found. Run the check again.", status=404, code="not_found"
        )
    if check.expires_at <= _now():
        raise TargetCheckError(
            "The target check expired (they last 30 minutes). Run the check again.",
            status=409,
            code="target_check_expired",
        )
    if (
        not check.result.get("extraction_ok", True)
        or not str(check.result.get("answer") or "").strip()
    ):
        raise TargetCheckError(
            "This check did not read an answer, so there is nothing to confirm. Fix the "
            "target settings and run the check again.",
            status=409,
            code="target_check_failed",
        )
    check.accepted = True
    check.accepted_at = _now()
    return check


def require_accepted_check(
    *,
    owner_id: uuid.UUID,
    check_id: str | None,
    snapshot: Mapping[str, Any],
) -> TargetCheck:
    """Gate a remote run on an accepted check of these exact settings."""
    if not check_id:
        raise TargetCheckError(
            "Check the target first: GreenLit sends one harmless request and shows you the "
            "answer it reads. Accept that reading, then start the full run.",
            code="target_check_required",
        )
    check = get_check(check_id, owner_id)
    if check is None:
        raise TargetCheckError(
            "That check was not found (or belongs to another account). Run the check again.",
            code="target_check_required",
        )
    if check.expires_at <= _now():
        raise TargetCheckError(
            "The target check expired (they last 30 minutes). Run the check again.",
            code="target_check_expired",
        )
    if check.config_hash != fingerprint(snapshot):
        raise TargetCheckError(
            "The target settings changed after the check, run the check again.",
            code="target_check_stale",
        )
    if not check.accepted:
        raise TargetCheckError(
            "Confirm that the extracted answer looks right before starting a full run.",
            code="target_check_not_accepted",
        )
    return check


@dataclass
class CheckOutcome:
    """What one check found, before it is stored."""

    request: dict[str, Any]
    status: int | None
    latency_ms: int | None
    answer: str
    answer_truncated: bool
    # True only when there is text that is not a web page: what a person may accept.
    extraction_ok: bool
    mapping_path: str | None
    hint: str | None
    error: dict[str, Any] | None = field(default=None)
    raw_response: dict[str, Any] | list[Any] | str | None = None


@dataclass
class AnswerCandidate:
    """One string value found in the JSON response that a person may inspect."""

    path: str
    preview: str


def _candidate_value(value: Any) -> str | None:
    """A printable preview of a JSON value for the answer-candidates list."""
    return value if isinstance(value, str) else None


def _answer_candidates_raw(data: Any, path: str = "", depth: int = 0) -> list[AnswerCandidate]:
    """Walk a JSON response and collect up to MAX_CANDIDATES string values.

    Depth-first, with list items rendered as ``a[0]`` style paths.
    """
    if depth >= _CANDIDATE_DEPTH:
        return []
    candidates: list[AnswerCandidate] = []
    if isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(value, dict):
                candidates.extend(_answer_candidates_raw(value, child_path, depth + 1))
                if len(candidates) >= MAX_CANDIDATES:
                    return candidates
            elif isinstance(value, list):
                for idx, item in enumerate(value):
                    elem_path = f"{child_path}[{idx}]"
                    if isinstance(item, (dict, list)):
                        candidates.extend(_answer_candidates_raw(item, elem_path, depth + 1))
                        if len(candidates) >= MAX_CANDIDATES:
                            return candidates
                    else:
                        text = _candidate_value(item)
                        if text is not None:
                            candidates.append(
                                AnswerCandidate(
                                    path=elem_path,
                                    preview=_redact(text, limit=MAX_CANDIDATE_PREVIEW),
                                )
                            )
                            if len(candidates) >= MAX_CANDIDATES:
                                return candidates
            else:
                text = _candidate_value(value)
                if text is not None:
                    candidates.append(
                        AnswerCandidate(
                            path=child_path,
                            preview=_redact(text, limit=MAX_CANDIDATE_PREVIEW),
                        )
                    )
                    if len(candidates) >= MAX_CANDIDATES:
                        return candidates
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            elem_path = f"{path}[{idx}]" if path else f"[{idx}]"
            if isinstance(item, (dict, list)):
                candidates.extend(_answer_candidates_raw(item, elem_path, depth + 1))
                if len(candidates) >= MAX_CANDIDATES:
                    return candidates
            else:
                text = _candidate_value(item)
                if text is not None:
                    candidates.append(
                        AnswerCandidate(
                            path=elem_path,
                            preview=_redact(text, limit=MAX_CANDIDATE_PREVIEW),
                        )
                    )
                    if len(candidates) >= MAX_CANDIDATES:
                        return candidates
    return candidates


def answer_candidates(data: Any) -> list[AnswerCandidate]:
    """Up to ``MAX_CANDIDATES`` string previews, redacted, for the response.

    Empty when the response is not JSON or holds no string values within
    depth ``_CANDIDATE_DEPTH``.
    """
    if not isinstance(data, (dict, list)):
        return []
    return _answer_candidates_raw(data)[:MAX_CANDIDATES]


def find_question_paths(data: Any, question_text: str) -> list[str]:
    """Return up to two exact-match paths to distinguish unique from ambiguous."""
    if not isinstance(data, (dict, list)):
        return []
    hits: list[str] = []

    def walk(value: Any, path: str = "", depth: int = 0) -> None:
        nonlocal hits
        if len(hits) > 1:
            return
        if depth > _CANDIDATE_DEPTH:
            return
        if isinstance(value, str) and value == question_text and path:
            hits.append(path)
            return
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                walk(child, child_path, depth + 1)
                if len(hits) > 1:
                    return
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                child_path = f"{path}[{idx}]" if path else f"[{idx}]"
                walk(child, child_path, depth + 1)
                if len(hits) > 1:
                    return

    walk(data)
    return hits


def find_question_path(data: Any, question_text: str) -> str | None:
    """Return the unique exact-match path, or ``None`` if absent or ambiguous."""
    paths = find_question_paths(data, question_text)
    return paths[0] if len(paths) == 1 else None


def run_check(
    snapshot: Mapping[str, Any],
    *,
    input_text: str,
    sender: Callable[[str], Trace] | None = None,
) -> CheckOutcome:
    """Send exactly one request and describe what came back.

    ``sender`` is injected by tests; the real path is the run's own connector,
    built from the same snapshot fields a run executes with.
    """
    check_snapshot = dict(snapshot)
    # A check is one request by definition: no retries, one at a time.
    check_snapshot["max_retries"] = 0
    check_snapshot["max_concurrency"] = 1
    target = str(check_snapshot.get("url") or "")
    request = _redacted_request(check_snapshot, input_text)
    mapping_path = str(check_snapshot.get("answer_path") or "") or None
    started = time.monotonic()
    answer = ""
    raw_response: dict[str, Any] | list[Any] | str | None = None
    status: int | None = None
    truncated = False
    error: dict[str, Any] | None = None
    latency_ms: int | None = None
    try:
        send = sender if sender is not None else _real_sender(check_snapshot)
        trace = send(input_text)
        answer = trace.output or ""
        if isinstance(trace.raw, (dict, list, str)):
            raw_response = trace.raw
        status = trace.status_code
        latency_ms = trace.latency_ms
    except ConnectorError as exc:
        status = _status_from(exc)
        latency_ms = int((time.monotonic() - started) * 1000)
        details = exc.details or {}
        error = error_detail(
            kind=exc.kind,
            message=exc.message,
            status=status,
            target=str(details.get("target") or target_of(target)),
            snippet=str(details.get("snippet") or ""),
            timeout_seconds=(
                details.get("timeout_seconds")
                if isinstance(details.get("timeout_seconds"), (int, float))
                else None
            ),
            # A refusal keeps the evidence it was diagnosed from: which CDN or
            # firewall answered, and whether a session was sent at all.
            headers=details.get("headers") if isinstance(details.get("headers"), dict) else None,
            evidence=(
                details.get("evidence") if isinstance(details.get("evidence"), list) else None
            ),
        )
    if len(answer) > MAX_ANSWER_CHARS:
        answer = answer[:MAX_ANSWER_CHARS].rstrip() + "…"
        truncated = True
    extraction_ok = error is None and bool(answer.strip()) and not _looks_like_html(answer)
    return CheckOutcome(
        request=request,
        status=status,
        latency_ms=latency_ms,
        answer=answer,
        answer_truncated=truncated,
        extraction_ok=extraction_ok,
        mapping_path=mapping_path,
        hint=None if error is not None else extraction_hint(answer, mapping_path),
        error=error,
        raw_response=raw_response,
    )


def _real_sender(snapshot: Mapping[str, Any]) -> Callable[[str], Trace]:
    """The connector a run would use for this exact snapshot."""
    from app.services.run_executor import build_sender

    def factory() -> Session:  # pragma: no cover - an HTTP sender never opens one
        raise RuntimeError("an HTTP sender needs no session")

    return build_sender(snapshot, factory)
