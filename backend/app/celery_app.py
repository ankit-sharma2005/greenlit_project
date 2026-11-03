"""Celery application for background work.

Run tasks live in :mod:`app.tasks`; autodiscovery imports that module when the
worker starts so ``celery -A app.celery_app.celery worker`` picks them up.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Celery
from celery.signals import worker_ready

from app.config import get_settings

settings = get_settings()

celery = Celery("greenlit", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
celery.autodiscover_tasks(["app"], related_name="tasks")

logger = logging.getLogger("greenlit.celery")


def _sweep_on_worker_start(**_kwargs: Any) -> None:
    """A restarted worker is exactly when a run can be left stranded (quirk 13)."""
    from app.db import SessionLocal
    from app.services.run_sweep import sweep_with_settings

    try:
        result = sweep_with_settings(SessionLocal)
    except Exception:  # a sweep must never stop the worker from starting
        logger.exception("The interrupted-run sweep failed at worker start")
        return
    if result["interrupted"]:
        logger.warning("Marked %s stranded run(s) interrupted", result["interrupted"])


# Assigned (not decorated) so mypy strict accepts it: the Celery API is untyped.
_sweep_on_start: Any = worker_ready.connect(_sweep_on_worker_start)
