from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_are_development_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APP_ENV",
        "DATABASE_URL",
        "REDIS_URL",
        "WEB_ORIGIN",
        "DEFAULT_TIMEOUT_SECONDS",
        "DEFAULT_RUN_PARALLELISM",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.is_development is True
    assert settings.default_timeout_seconds == 60
    assert settings.default_run_parallelism == 2
    assert settings.cors_origins == ["http://localhost:5177"]


def test_cors_origins_accepts_comma_separated_values() -> None:
    settings = Settings(_env_file=None, web_origin="http://a.test, http://b.test")

    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_timeout_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, default_timeout_seconds=0)


def test_secret_key_has_minimum_length() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_secret_key="short")
