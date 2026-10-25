"""Celery tasks: runs execute here, never inside an HTTP request (spec 8.1).

The task body is deliberately thin — all orchestration, error isolation and
scoring live in :func:`app.services.run_executor.execute_run`, which the tests
call directly with injected fakes.
"""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery
from app.services.run_executor import execute_run

logger = logging.getLogger("greenlit.tasks")


def execute_run_task(run_id: str) -> dict[str, Any]:
    """Execute one queued run with the real session factory and Redis progress."""
    logger.info("Worker picked up run %s", run_id)
    return execute_run(run_id)


# Assigned (not decorated) so mypy strict accepts it: the Celery API is untyped.
run_test: Any = celery.task(name="app.tasks.run_test")(execute_run_task)
