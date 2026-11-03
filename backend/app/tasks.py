"""Celery tasks: runs execute here, never inside an HTTP request (spec 8.1).

The task body is deliberately thin — all orchestration, error isolation and
scoring live in :func:`app.services.run_executor.execute_run`, which the tests
call directly with injected fakes.
"""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery
from app.db import SessionLocal
from app.services.run_executor import execute_run
from app.services.run_sweep import sweep_with_settings

logger = logging.getLogger("greenlit.tasks")


def _sweep_quietly() -> None:
    """Clear runs a dead worker left behind, without failing the new task."""
    try:
        result = sweep_with_settings(SessionLocal)
    except Exception:
        logger.exception("The interrupted-run sweep failed before a run started")
        return
    if result["interrupted"]:
        logger.warning("Marked %s stranded run(s) interrupted", result["interrupted"])


def execute_run_task(run_id: str) -> dict[str, Any]:
    """Execute one queued run with the real session factory and Redis progress.

    The sweep runs first so a stranded run is cleared even when no worker
    restart happened; the task's own run is still ``queued`` and is never swept.
    """
    logger.info("Worker picked up run %s", run_id)
    _sweep_quietly()
    return execute_run(run_id)


def sweep_stale_task() -> dict[str, Any]:
    """Mark runs whose worker went quiet as interrupted (quirk 13)."""
    return sweep_with_settings(SessionLocal)


# Assigned (not decorated) so mypy strict accepts it: the Celery API is untyped.
run_test: Any = celery.task(name="app.tasks.run_test")(execute_run_task)
sweep_stale: Any = celery.task(name="app.tasks.sweep_stale")(sweep_stale_task)
