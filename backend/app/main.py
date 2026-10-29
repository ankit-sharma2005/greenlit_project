"""GreenLit API entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.connectors import router as connectors_router
from app.api.datasets import router as datasets_router
from app.api.demo import router as demo_router
from app.api.evaluations import router as evaluations_router
from app.api.health import router as health_router
from app.api.judge_profiles import router as judge_profiles_router
from app.api.labels import router as labels_router
from app.api.providers import router as providers_router
from app.api.runs import router as runs_router
from app.api.users import router as users_router
from app.config import Settings, get_settings
from app.errors import install_error_handlers

logger = logging.getLogger("greenlit")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application."""
    resolved = settings or get_settings()
    logging.basicConfig(level=resolved.log_level.upper())

    app = FastAPI(
        title="GreenLit API",
        version="0.1.0",
        description="Pre-launch testing and evaluation for LLM-powered applications.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(providers_router)
    app.include_router(judge_profiles_router)
    app.include_router(labels_router)
    app.include_router(datasets_router)
    app.include_router(connectors_router)
    app.include_router(evaluations_router)
    app.include_router(runs_router)
    app.include_router(demo_router)
    app.include_router(audit_router)

    logger.info("GreenLit API created (env=%s)", resolved.app_env)
    return app


app = create_app()


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    """Tiny landing response; the UI runs separately."""
    return {"service": "greenlit-api", "docs": "/docs", "health": "/healthz"}
