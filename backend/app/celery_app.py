"""Celery application for background work.

Run tasks live in :mod:`app.tasks`; autodiscovery imports that module when the
worker starts so ``celery -A app.celery_app.celery worker`` picks them up.
"""

from __future__ import annotations

from celery import Celery

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
