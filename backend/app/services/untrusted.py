"""One place for text that comes from outside GreenLit (PART 2, step 6.1).

Pure functions, no I/O and no model calls:

- `sanitize_text` strips control, zero-width and bidi characters and HTML tags, collapses
  whitespace and caps the length.
- `scrub_secrets` replaces key-shaped strings so a provider key, bearer token or cookie
  cannot travel into a prompt.
- `make_envelope` wraps untrusted content in a delimiter carrying a per-request nonce, and
  neutralises the delimiter, the nonce and role markers found inside the content, so the
  content cannot close its own block or pretend to be a message from the system.
- `scan_output` rejects model output containing URLs, markdown links or images, HTML, code
  fences with shell content, secret-shaped strings, the canary, or too much text.
- `build_analyst_input` builds the one input an explanation may be based on, from structured
  run data only: ids, numbers and truncated redacted snippets.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

MAX_SNIPPET_CHARS = 300
MAX_OUTPUT_CHARS = 4_000
MAX_INPUT_CHARS = 12_000

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]{0,200}>")
_WHITESPACE = re.compile(r"[ \t\f\v]+")

# Any data tag, with or without attributes: `<data nonce="forged">` is just as good a
# breakout as `</data>`, and the test that found this was right to insist on it.
_DELIMITER_TAG = re.compile(r"</?data\b[^>]*>?", re.IGNORECASE)
_NONCE_TAG = re.compile(r"</?nonce\b[^>]*>?", re.IGNORECASE)

_ROLE_MARKERS = (
    "<system>",
    "</system>",
    "system:",
    "assistant:",
    "developer:",
    "user:",
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*[\"']?[A-Za-z0-9._\-]{6,}"
    ),
    re.compile(r"(?i)\bcookie:\s*\S+=\S+"),
    re.compile(r"(?i)\bset-cookie:\s*\S+"),
)

_URL = re.compile(r"(?i)\b(?:https?|ftp)://\S+|\bwww\.\S+")
_MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]{0,200}\]\([^)\n]{0,500}\)")
_FENCE = re.compile(r"```")
_SHELL = re.compile(r"(?i)\b(?:curl|wget|bash|sh|powershell|rm|chmod|nc)\b")


def sanitize_text(text: str, limit: int = MAX_SNIPPET_CHARS) -> str:
    """Strip control, zero-width and bidi characters and tags; collapse spaces; cap length."""
    if not isinstance(text, str):
        text = str(text)
    cleaned = _CONTROL.sub("", text)
    cleaned = _ZERO_WIDTH.sub("", cleaned)
    cleaned = _HTML_TAG.sub("", cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned)
    cleaned = "\n".join(line.strip() for line in cleaned.splitlines())
    cleaned = cleaned.strip()
    if limit > 0 and len(cleaned) > limit:
        return cleaned[:limit].rstrip() + "…"
    return cleaned


def scrub_secrets(text: str) -> str:
    """Replace key-shaped strings with `[redacted]`."""
    cleaned = text
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned


def make_envelope(
    content: str, nonce: str | None = None, *, attribute: bool = True
) -> tuple[str, str]:
    """Wrap untrusted content so it cannot break out of its block or impersonate a role.

    Returns the wrapped text and the nonce used. The nonce appears in the opening tag only;
    every copy of it, of the delimiter, of a nonce tag and of a role marker inside the content
    is replaced.

    ``attribute=False`` writes the nonce on its own line inside the block instead of in the
    opening tag. Some callers must keep the opening tag exactly `<data>` (the judge prompt
    has done so since M7 and its tests pin it), and the nonce travels just as well inside.
    """
    chosen = nonce or secrets.token_hex(12)
    body = _DELIMITER_TAG.sub("[marker removed]", content)
    body = _NONCE_TAG.sub("[marker removed]", body)
    for marker in _ROLE_MARKERS:
        body = re.sub(re.escape(marker), "[marker removed]", body, flags=re.IGNORECASE)
    body = body.replace(chosen, "[nonce removed]")
    if attribute:
        return f'<data nonce="{chosen}">\n{body}\n</data>', chosen
    return f"<data>\n<nonce>{chosen}</nonce>\n{body}\n</data>", chosen


def scan_output(
    text: str,
    *,
    canary: str | None = None,
    max_chars: int = MAX_OUTPUT_CHARS,
) -> tuple[bool, str]:
    """Check model output. Returns (allowed, reason); reason is "" when allowed."""
    if canary and canary in text:
        return False, "canary"
    if len(text) > max_chars:
        return False, "too_long"
    if _MARKDOWN_LINK.search(text):
        return False, "markdown_link"
    if _URL.search(text):
        return False, "url"
    if _FENCE.search(text) and _SHELL.search(text):
        return False, "shell"
    if _HTML_TAG.search(text):
        return False, "html"
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return False, "secret"
    return True, ""


# Text aimed at the judge rather than at the question. This is a NON-verdict signal: it is
# reported on the case, and it changes no score, no metric and no verdict.
_JUDGE_DIRECTED: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)ignore (?:the |your )?(?:rubric|instructions?|rules?|scoring|criteria)"),
    re.compile(r"(?i)\bscore (?:this |it |me )?(?:as )?1(?:\.0+)?\b"),
    re.compile(r"(?i)\bmark (?:this|it) (?:as )?(?:a )?pass\b"),
    re.compile(r"(?i)\byou are (?:the |a )?judge\b"),
    re.compile(r"(?i)\b(?:award|give) (?:this|it) (?:a )?(?:full|perfect|max\w*) score\b"),
    re.compile(r"(?i)\boverride (?:the )?(?:score|verdict|rubric)\b"),
    re.compile(r"(?i)\bdo not penalise\b|\bdo not penalize\b"),
)


def detect_judge_manipulation(text: str | None) -> bool:
    """True when an answer contains text addressed to the judge.

    Derived at read time from the stored answer, so no column and no migration is needed and
    a run recorded before this flag existed is reported the same way. It never feeds a score
    or a verdict; it is shown to the person reading the case.
    """
    if not text:
        return False
    return any(pattern.search(text) for pattern in _JUDGE_DIRECTED)


def _number(value: Any) -> str:
    """A number exactly as the backend holds it; anything else is written as unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "unknown"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def build_analyst_input(
    *,
    run_id: str,
    verdict: str | None,
    score: float | None,
    criteria_profile: str,
    metrics: Sequence[Mapping[str, Any]],
    failed_cases: Sequence[Mapping[str, Any]],
    nonce: str | None = None,
) -> str:
    """The only input an explanation may be built from: structured fields, redacted snippets.

    No keys, cookies, headers, connector configuration, other runs or other users are
    accepted by this function at all — it takes exactly the fields below.
    """
    lines = [
        "RUN",
        f"id: {sanitize_text(run_id, 64)}",
        f"verdict: {sanitize_text(verdict or 'none', 20)}",
        f"score: {_number(score)}",
        f"criteria_profile: {sanitize_text(criteria_profile, 60)}",
        "",
        "METRICS",
    ]
    for metric in list(metrics)[:30]:
        name = sanitize_text(str(metric.get("name", "")), 60)
        instrumented = metric.get("instrumented") is True
        lines.append(
            f"- {name}: score={_number(metric.get('score')) if instrumented else 'not measured'} "
            f"weight={_number(metric.get('weight'))} "
            f"hard_gate={str(metric.get('hard_gate') is True).lower()} "
            f"passed={str(metric.get('passed') is True).lower() if instrumented else 'unknown'}"
        )

    case_lines = []
    for case in list(failed_cases)[:20]:
        question = scrub_secrets(sanitize_text(str(case.get("input", "")), MAX_SNIPPET_CHARS))
        actual = scrub_secrets(sanitize_text(str(case.get("actual", "")), MAX_SNIPPET_CHARS))
        reason = scrub_secrets(sanitize_text(str(case.get("reason", "")), 120))
        case_lines.append(f"- question: {question}\n  actual: {actual}\n  reason: {reason}")

    body = "\n".join(lines) + "\n\nFAILED CASES (untrusted)\n"
    body += "\n".join(case_lines) if case_lines else "(none)"
    # Same shape as the judge prompt: `<data>` on its own, the nonce on the next line, so the
    # cache key can normalise it and the system prompt's `<nonce>` sentence is accurate.
    wrapped, _ = make_envelope(body, nonce, attribute=False)
    # The whole input is bounded even when every field is at its own cap.
    return wrapped[:MAX_INPUT_CHARS]
