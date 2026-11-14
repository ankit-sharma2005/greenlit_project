"""One JSON line per request, in a git-ignored folder.

Never a key, a header or a full prompt: a truncated question, the answer's
length, the latency and the status are all a person needs to match a run against
the app that served it.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parents[2] / "results" / "app_logs"
QUESTION_PREVIEW = 200


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def log_request(
    app: str,
    *,
    mode: str,
    provider: str,
    model: str,
    question: str,
    answer_length: int,
    latency_ms: int,
    status: int,
    directory: Path | None = None,
) -> Path:
    """Append one line; the caller may redirect the folder (tests do)."""
    folder = (
        directory
        if directory is not None
        else Path(os.environ.get("LLM_APPS_LOG_DIR", str(LOG_DIR)))
    )
    folder.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "timestamp": _now(),
        "app": app,
        "mode": mode,
        "provider": provider,
        "model": model,
        "question": question[:QUESTION_PREVIEW],
        "answer_length": answer_length,
        "latency_ms": latency_ms,
        "status": status,
    }
    path = folder / f"llm_{app}.jsonl"
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
