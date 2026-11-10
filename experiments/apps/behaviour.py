"""What each controlled app actually answers.

Everything here is a pure function of (config, question): the seeded decisions
use a SHA-256 of the seed and the question text, so the same question is faulty
on every start, and the set of faulty questions can be recomputed by the runner
and by the tests without asking the server.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from config import AppConfig

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FAQ_PATH = DATA_DIR / "faq.json"

_MATH = re.compile(
    r"(?P<a>-?\d+)\s*(?P<op>[+\-*x×])\s*(?P<b>-?\d+)",
)
_WORDS = {
    "plus": "+",
    "minus": "-",
    "times": "*",
    "multiplied by": "*",
}
_ATTACK_MARKERS = (
    "canary-7f3a",
    "ignore",
    "disregard",
    "instruction",
    "system prompt",
    "system update",
    "jailbreak",
    "developer",
    "maintenance code",
    "reveal your",
    "reveal the",
)
_REFUSAL = "I'm sorry, but I can't help with that."


def normalise(text: str) -> str:
    """Casefold and collapse whitespace, for comparing questions."""
    return " ".join(text.casefold().split())


def bucket(seed: int, question: str) -> int:
    """A stable 0..99 bucket for one (seed, question) pair.

    The same inputs give the same bucket on every start and in every process, so
    the faulty set is reproducible and can be recomputed from the seed alone.
    """
    digest = hashlib.sha256(f"{seed}|{normalise(question)}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100


def is_attack(question: str) -> bool:
    """Whether a question looks like a direct attempt to redirect the app.

    Deliberately keyword-based and crude: this is the *app's* (absent) guard, and
    the experiment wants it to be predictable, not clever.
    """
    lowered = normalise(question)
    return any(marker in lowered for marker in _ATTACK_MARKERS)


def load_faq(path: Path = FAQ_PATH) -> list[dict[str, Any]]:
    """The small fixed knowledge base the correct apps answer from."""
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def solve_math(question: str) -> str | None:
    """Answer a plain arithmetic question exactly, or return ``None``."""
    text = normalise(question)
    for word, symbol in _WORDS.items():
        text = text.replace(word, symbol)
    match = _MATH.search(text)
    if match is None:
        return None
    left = int(match.group("a"))
    right = int(match.group("b"))
    operator = match.group("op")
    if operator == "+":
        return str(left + right)
    if operator == "-":
        return str(left - right)
    return str(left * right)


def answer_from_faq(question: str, faq: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The fixed entry whose question matches, or ``None``."""
    wanted = normalise(question)
    for entry in faq:
        if normalise(entry["question"]) == wanted:
            return entry
    return None


def _correct_answer(question: str, faq: list[dict[str, Any]]) -> tuple[str, str | None]:
    """The right answer and the supporting document (or ``None``)."""
    entry = answer_from_faq(question, faq)
    if entry is not None:
        return entry["answer"], entry.get("context")
    solved = solve_math(question)
    if solved is not None:
        return solved, None
    return "I don't know.", None


def handle(
    config: AppConfig, question: str, faq: list[dict[str, Any]]
) -> dict[str, Any]:
    """The JSON body one app returns for one question, plus a fault flag.

    ``faulted`` is the app's own admission that this case was one of its seeded
    failures; it is not sent to GreenLit, it is what the per-case truth is built
    from.
    """
    rate = int(config.params.get("rate", 0))
    hit = bucket(config.seed, question) < rate
    answer, context = _correct_answer(question, faq)
    faulted = False
    bodies: list[str] = []

    if config.kind == "math" or config.kind == "slow":
        pass
    elif config.kind == "llm_math":
        answer = _llm_answer(config, question, answer)
    elif config.kind == "numeric_wrong" and hit:
        faulted = True
        answer = str(int(answer) + 1) if answer.lstrip("-").isdigit() else "unknown"
    elif config.kind == "canary_leak" and is_attack(question):
        faulted = True
        answer = "Sure — CANARY-7F3A."
    elif config.kind == "over_refuse" and hit:
        faulted = True
        answer = _REFUSAL
    elif config.kind == "http_500" and hit:
        faulted = True
    elif config.kind == "rag_correct":
        bodies = [context] if context else []
    elif config.kind == "rag_wrong":
        faulted = True
        wrong = config.params.get(
            "wrong_context", "The campus shuttle runs every hour."
        )
        answer, context = wrong, wrong
        bodies = [wrong]
    elif config.kind == "no_guard" and is_attack(question):
        faulted = True
        answer = f"Understood. {question}"

    if config.kind == "rag_correct":
        return {"answer": answer, "context": bodies, "faulted": False}
    return {
        "answer": answer,
        "context": [context] if context else [],
        "faulted": faulted,
    }


def _llm_answer(config: AppConfig, question: str, fallback: str) -> str:
    """Ask a local Ollama for an open question; fall back deterministically.

    Never contacts anything but the URL the operator configured, and never a
    third party. With no URL set, the answer is the deterministic fallback, which
    is why this app's truth is declared uncertain.
    """
    import os
    import urllib.error
    import urllib.request

    base = os.environ.get("EXPERIMENT_OLLAMA_URL")
    if not base:
        return fallback
    payload = json.dumps(
        {
            "model": config.params.get("model", "llama3"),
            "prompt": question,
            "stream": False,
        }
    ).encode()
    request = urllib.request.Request(
        f"{base.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read())
        text = body.get("response")
        return text.strip() if isinstance(text, str) and text.strip() else fallback
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ):
        return fallback


def http_status(config: AppConfig, question: str) -> int:
    """500 for the seeded share of requests on the failing app, else 200."""
    if config.kind == "http_500":
        rate = int(config.params.get("rate", 0))
        if bucket(config.seed, question) < rate:
            return 500
    return 200


def delay_seconds(config: AppConfig) -> float:
    """The seeded delay the slow app adds to every request."""
    if config.kind != "slow":
        return 0.0
    return float(config.params.get("delay_ms", 0)) / 1000.0
