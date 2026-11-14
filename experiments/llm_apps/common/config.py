"""Provider and app settings, loaded from the environment only.

The key for a hosted provider is read from an environment variable and is never
printed, logged, returned by an endpoint or written to a file. The two providers
here are the ones the task names: a local Ollama (no key) and Groq (key from
``GROQ_API_KEY``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "hermes3:8b",
        "key_env": "",
        # A cold local model can take a while to load before it answers.
        "timeout_seconds": 120.0,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
        "timeout_seconds": 60.0,
    },
}

# Connecting to a local or hosted provider is quick; only reading the answer may wait.
CONNECT_TIMEOUT_SECONDS = 10.0

MODES = ("guarded", "weak")


class ConfigError(Exception):
    """The environment asks for something this app cannot do."""


@dataclass(frozen=True)
class Settings:
    """Everything one app process needs; no field holds a secret's value twice."""

    provider: str
    base_url: str
    model: str
    temperature: float
    timeout_seconds: float
    max_tokens: int
    mode: str
    question_limit: int
    body_limit: int
    api_key: str

    def public(self) -> dict[str, str]:
        """What /health may say: never the key."""
        return {"mode": self.mode, "provider": self.provider, "model": self.model}

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}


def _number(value: str | None, default: float, name: str) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return parsed


def _timeout(value: str | None, default: float, name: str) -> float:
    """A bad value is not fatal: use the provider's default and say so once."""
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except ValueError:
        logger.warning(
            "%s=%r is not a number; using the default %gs", name, value, default
        )
        return default
    if parsed <= 0:
        logger.warning(
            "%s=%r is not positive; using the default %gs", name, value, default
        )
        return default
    return parsed


def _integer(value: str | None, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a whole number") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return parsed


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read the environment once; raise a message that never quotes a secret."""
    source = os.environ if env is None else env
    provider = (source.get("LLM_PROVIDER") or "ollama").strip().lower()
    if provider not in DEFAULT_PROVIDERS:
        raise ConfigError(f"LLM_PROVIDER must be one of {sorted(DEFAULT_PROVIDERS)}")
    defaults = DEFAULT_PROVIDERS[provider]

    mode = (source.get("APP_MODE") or "guarded").strip().lower()
    if mode not in MODES:
        raise ConfigError(f"APP_MODE must be one of {list(MODES)}")

    key_env = defaults["key_env"]
    api_key = (source.get(key_env) or "").strip() if key_env else ""
    if key_env and not api_key:
        raise ConfigError(f"{key_env} is required when LLM_PROVIDER={provider}")

    base_url = (source.get("LLM_BASE_URL") or defaults["base_url"]).strip()
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError("LLM_BASE_URL must start with http:// or https://")
    model = (source.get("LLM_MODEL") or defaults["model"]).strip()
    if not model:
        raise ConfigError("LLM_MODEL must not be empty")

    return Settings(
        provider=provider,
        base_url=base_url.rstrip("/"),
        model=model,
        temperature=_number(source.get("LLM_TEMPERATURE"), 0.0, "LLM_TEMPERATURE"),
        timeout_seconds=_timeout(
            source.get("LLM_TIMEOUT_SECONDS"),
            float(defaults["timeout_seconds"]),
            "LLM_TIMEOUT_SECONDS",
        ),
        max_tokens=_integer(source.get("LLM_MAX_TOKENS"), 512, "LLM_MAX_TOKENS"),
        mode=mode,
        question_limit=_integer(
            source.get("MAX_QUESTION_CHARS"), 2000, "MAX_QUESTION_CHARS"
        ),
        body_limit=_integer(source.get("MAX_BODY_BYTES"), 64_000, "MAX_BODY_BYTES"),
        api_key=api_key,
    )
