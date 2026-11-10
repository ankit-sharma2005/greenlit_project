"""Load and validate one experiment app's declared configuration.

The ground truth is declared *before* any run: :func:`validate_config` refuses a
config without an ``expected_verdict`` and an ``expected_reason``, so a variant
can never be added after looking at what GreenLit said about it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERDICTS = ("GO", "REVIEW", "NO_GO", "UNCERTAIN")
KINDS = (
    "math",
    "llm_math",
    "numeric_wrong",
    "canary_leak",
    "over_refuse",
    "slow",
    "http_500",
    "rag_correct",
    "rag_wrong",
    "no_guard",
)
CONFIG_DIR = Path(__file__).resolve().parent / "app_config"


class ConfigError(ValueError):
    """A variant config is incomplete or contradicts the experiment design."""


@dataclass(frozen=True)
class AppConfig:
    """One controlled app: what it does, and what it *should* be judged as."""

    id: str
    port: int
    fault: str
    seed: int
    expected_verdict: str
    expected_reason: str
    truth_notes: str
    kind: str
    uncertain_truth: bool
    params: dict[str, Any]

    def ground_truth_entry(self) -> dict[str, Any]:
        """The declared truth as it is written to ``data/ground_truth.json``."""
        return {
            "id": self.id,
            "port": self.port,
            "fault": self.fault,
            "seed": self.seed,
            "kind": self.kind,
            "expected_verdict": self.expected_verdict,
            "expected_reason": self.expected_reason,
            "truth_notes": self.truth_notes,
            "uncertain_truth": self.uncertain_truth,
        }


def validate_config(data: dict[str, Any], source: str) -> AppConfig:
    """Return a config or raise :class:`ConfigError` naming the offending field."""
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: a config must be a JSON object")
    for field in (
        "id",
        "port",
        "fault",
        "seed",
        "expected_reason",
        "truth_notes",
        "kind",
    ):
        if field not in data:
            raise ConfigError(f"{source}: missing required field {field!r}")
    if data.get("expected_verdict") not in VERDICTS:
        raise ConfigError(
            f"{source}: expected_verdict must be one of {VERDICTS}, "
            f"got {data.get('expected_verdict')!r} — declare it before any run"
        )
    if data["kind"] not in KINDS:
        raise ConfigError(f"{source}: unknown kind {data['kind']!r}")
    if not isinstance(data["port"], int) or not 1024 <= data["port"] <= 65535:
        raise ConfigError(f"{source}: port must be an integer above 1023")
    uncertain = bool(data.get("uncertain_truth", False))
    if uncertain and data["expected_verdict"] != "UNCERTAIN":
        raise ConfigError(
            f"{source}: an uncertain_truth app must declare expected_verdict UNCERTAIN"
        )
    if not uncertain and data["expected_verdict"] == "UNCERTAIN":
        raise ConfigError(f"{source}: UNCERTAIN requires uncertain_truth: true")
    params = data.get("params", {})
    if not isinstance(params, dict):
        raise ConfigError(f"{source}: params must be an object")
    return AppConfig(
        id=str(data["id"]),
        port=int(data["port"]),
        fault=str(data["fault"]),
        seed=int(data["seed"]),
        expected_verdict=str(data["expected_verdict"]),
        expected_reason=str(data["expected_reason"]),
        truth_notes=str(data["truth_notes"]),
        kind=str(data["kind"]),
        uncertain_truth=uncertain,
        params=params,
    )


def load_config(path: Path) -> AppConfig:
    """Read and validate one ``app_config/appNN.json`` file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read config: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON: {exc}") from exc
    return validate_config(data, str(path))


def load_all(directory: Path = CONFIG_DIR) -> list[AppConfig]:
    """Every declared variant, in id order."""
    configs = [load_config(path) for path in sorted(directory.glob("app*.json"))]
    if not configs:
        raise ConfigError(f"{directory}: no app*.json configs found")
    seen: set[str] = set()
    ports: set[int] = set()
    for config in configs:
        if config.id in seen:
            raise ConfigError(f"{directory}: duplicate app id {config.id!r}")
        if config.port in ports:
            raise ConfigError(f"{directory}: duplicate port {config.port}")
        seen.add(config.id)
        ports.add(config.port)
    return configs
