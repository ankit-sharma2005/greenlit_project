"""Load and validate the versioned safety sets (spec 8.3).

The two JSON files under ``data/`` are the built-in sets: they ship with the
app, carry a ``version`` field, and are validated on load so a broken or
truncated set fails loudly instead of silently scoring a run.

Each attack case is decided by a rule, never by a model:

* a case with a ``canary`` fails when that marker shows up in the app's output
  (the app echoed or leaked the planted secret);
* a case with ``expects_refusal`` fails when the app's output is not a refusal
  (it answered disallowed content instead of declining).

``critical`` marks the cases where a failure is a hard gate: a leaked secret
and a missing refusal for disallowed content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
ATTACKS_FILE = DATA_DIR / "attacks.json"
SAFE_PROMPTS_FILE = DATA_DIR / "safe_prompts.json"

MIN_ATTACK_COUNT = 40
MIN_SAFE_PROMPT_COUNT = 20

ATTACK_CATEGORIES: tuple[str, ...] = (
    "direct_injection",
    "indirect_injection",
    "system_prompt_leak",
    "jailbreak",
    "disallowed_content",
)


class SafetySetError(ValueError):
    """A safety set is missing, malformed or too small to be useful."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class AttackCase:
    """One built-in attack and the rule that decides whether it succeeded."""

    id: str
    category: str
    prompt: str
    canary: str | None
    expects_refusal: bool
    critical: bool


@dataclass(frozen=True)
class SafePrompt:
    """A harmless request that must be answered, to measure over-refusal."""

    id: str
    prompt: str


@dataclass(frozen=True)
class AttackSet:
    version: str
    marker: str | None
    cases: tuple[AttackCase, ...]

    def by_id(self) -> dict[str, AttackCase]:
        return {case.id: case for case in self.cases}

    def critical_ids(self) -> tuple[str, ...]:
        return tuple(case.id for case in self.cases if case.critical)


@dataclass(frozen=True)
class SafePromptSet:
    version: str
    prompts: tuple[SafePrompt, ...]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SafetySetError(f"Could not read the safety set {path.name}: {exc}.") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SafetySetError(f"The safety set {path.name} is not valid JSON: {exc.msg}.") from exc
    if not isinstance(payload, dict):
        raise SafetySetError(f"The safety set {path.name} must be a JSON object.")
    return payload


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SafetySetError(message)


def parse_attack_set(payload: dict[str, Any]) -> AttackSet:
    """Validate one decoded attacks file (also used by the tests)."""
    version = str(payload.get("version") or "").strip()
    _require(bool(version), "The attack set needs a version.")
    marker_raw = payload.get("marker")
    marker = str(marker_raw).strip() if marker_raw else None
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise SafetySetError("The attack set needs a 'cases' list.")

    cases: list[AttackCase] = []
    seen: set[str] = set()
    categories: set[str] = set()
    for index, entry in enumerate(raw_cases):
        _require(isinstance(entry, dict), f"Attack {index} must be an object.")
        case_id = str(entry.get("id") or "").strip()
        _require(bool(case_id), f"Attack {index} has no id.")
        _require(case_id not in seen, f"Duplicate attack id '{case_id}'.")
        seen.add(case_id)
        category = str(entry.get("category") or "").strip()
        _require(
            category in ATTACK_CATEGORIES,
            f"Attack '{case_id}' has unknown category '{category}'.",
        )
        categories.add(category)
        prompt = str(entry.get("prompt") or "").strip()
        _require(bool(prompt), f"Attack '{case_id}' has no prompt.")
        canary_raw = entry.get("canary")
        canary = str(canary_raw).strip() if canary_raw else None
        expects_refusal = bool(entry.get("expects_refusal"))
        critical = bool(entry.get("critical"))
        _require(
            canary is not None or expects_refusal,
            f"Attack '{case_id}' needs a canary or an expected refusal to be rule-decidable.",
        )
        _require(
            not (canary is not None and expects_refusal),
            f"Attack '{case_id}' cannot both leak a marker and expect a refusal.",
        )
        if expects_refusal and canary is None:
            _require(
                category == "disallowed_content",
                f"Attack '{case_id}' expects a refusal but is not a disallowed-content case.",
            )
        if category == "disallowed_content":
            _require(
                expects_refusal and canary is None,
                f"Disallowed-content attack '{case_id}' must only check for a refusal.",
            )
        cases.append(
            AttackCase(
                id=case_id,
                category=category,
                prompt=prompt,
                canary=canary,
                expects_refusal=expects_refusal,
                critical=critical,
            )
        )

    _require(
        len(cases) >= MIN_ATTACK_COUNT,
        f"The attack set needs at least {MIN_ATTACK_COUNT} cases; it has {len(cases)}.",
    )
    missing = [name for name in ATTACK_CATEGORIES if name not in categories]
    _require(not missing, f"The attack set is missing categories: {', '.join(missing)}.")
    _require(
        any(case.critical for case in cases),
        "The attack set needs at least one critical case to act as a hard gate.",
    )
    return AttackSet(version=version, marker=marker, cases=tuple(cases))


def parse_safe_prompt_set(payload: dict[str, Any]) -> SafePromptSet:
    """Validate one decoded safe-prompts file (also used by the tests)."""
    version = str(payload.get("version") or "").strip()
    _require(bool(version), "The safe-prompt set needs a version.")
    raw_prompts = payload.get("prompts")
    if not isinstance(raw_prompts, list):
        raise SafetySetError("The safe-prompt set needs a 'prompts' list.")
    prompts: list[SafePrompt] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw_prompts):
        _require(isinstance(entry, dict), f"Safe prompt {index} must be an object.")
        prompt_id = str(entry.get("id") or "").strip()
        _require(bool(prompt_id), f"Safe prompt {index} has no id.")
        _require(prompt_id not in seen, f"Duplicate safe-prompt id '{prompt_id}'.")
        seen.add(prompt_id)
        text = str(entry.get("prompt") or "").strip()
        _require(bool(text), f"Safe prompt '{prompt_id}' has no text.")
        prompts.append(SafePrompt(id=prompt_id, prompt=text))
    _require(
        len(prompts) >= MIN_SAFE_PROMPT_COUNT,
        f"The safe-prompt set needs at least {MIN_SAFE_PROMPT_COUNT} prompts; "
        f"it has {len(prompts)}.",
    )
    return SafePromptSet(version=version, prompts=tuple(prompts))


@lru_cache(maxsize=1)
def load_attack_set() -> AttackSet:
    """The built-in attack set, validated once per process."""
    return parse_attack_set(_read_json(ATTACKS_FILE))


@lru_cache(maxsize=1)
def load_safe_prompt_set() -> SafePromptSet:
    """The built-in safe-prompt set, validated once per process."""
    return parse_safe_prompt_set(_read_json(SAFE_PROMPTS_FILE))
