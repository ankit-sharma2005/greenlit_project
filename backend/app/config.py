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
    debug: bool = Field(default=False, description="debug")
    log_level: str = "INFO"

    # Used later to encrypt provider/connector secrets at rest.
    app_secret_key: str = Field(default="dev-insecure-key-change-me-0123456789", min_length=8)

    database_url: str = "postgresql+psycopg://greenlit:greenlit@localhost:5436/greenlit"
    redis_url: str = "redis://localhost:6382/0"

    web_origin: str = "http://localhost:5177"

    default_timeout_seconds: int = Field(default=60, ge=1, le=600)
    default_run_parallelism: int = Field(default=2, ge=1, le=16)
    # A run with no heartbeat for this long is marked "interrupted" (quirk 13).
    interrupted_after_minutes: int = Field(default=10, ge=1, le=240)

    # --- Accounts and sessions (M1) ---
    access_token_expire_minutes: int = Field(default=15, ge=1, le=240)
    refresh_token_expire_days: int = Field(default=14, ge=1, le=90)
    password_reset_expire_minutes: int = Field(default=30, ge=5, le=240)
    login_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    login_rate_limit_window_seconds: int = Field(default=900, ge=60, le=86400)
    # None means "auto": Secure cookies only when the request arrived over HTTPS.
    cookie_secure: bool | None = None

    # --- Provider defaults (M2) ---
    provider_timeout_seconds: int = Field(default=30, ge=1, le=300)
    provider_max_retries: int = Field(default=3, ge=0, le=10)
    provider_backoff_factor: float = Field(default=2.0, ge=1.0, le=10.0)

    # --- Built-in demo (M10, spec section 10) ---
    # The demo helpdesk runs as its own Compose service (profile ``demo``):
    # one instance answering correctly, one returning broken answers.
    demo_app_url: str = "http://demo-app:9000/chat"
    demo_app_broken_url: str = "http://demo-app-broken:9000/chat"

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
