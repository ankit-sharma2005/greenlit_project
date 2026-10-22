"""Application settings.

All configuration comes from environment variables (see ``.env.example``). Defaults are
development-friendly so the API starts inside Docker Compose without extra setup.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the API and workers."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    log_level: str = "INFO"

    # Used later to encrypt provider/connector secrets at rest.
    app_secret_key: str = Field(default="dev-insecure-key-change-me", min_length=8)

    database_url: str = "postgresql+psycopg://greenlit:greenlit@localhost:5432/greenlit"
    redis_url: str = "redis://localhost:6379/0"

    web_origin: str = "http://localhost:5173"

    default_timeout_seconds: int = Field(default=60, ge=1, le=600)
    default_run_parallelism: int = Field(default=2, ge=1, le=16)

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "local"}

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.web_origin.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
