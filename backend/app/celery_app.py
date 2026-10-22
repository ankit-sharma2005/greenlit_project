"""Celery application for background work.

M0 only wires the broker so the ``worker`` service starts; run tasks arrive in M6.
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
