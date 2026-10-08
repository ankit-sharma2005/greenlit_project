from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Protocol, TypeVar, cast
from uuid import uuid4

from celery import Celery  # type: ignore[import-untyped]

from app.config import settings


class CeleryConfiguration(Protocol):
    def update(self, **options: object) -> None: ...


class CeleryRequest(Protocol):
    id: str | None


class CeleryTaskContext(Protocol):
    request: CeleryRequest


class CeleryRuntime(Protocol):
    conf: CeleryConfiguration

    def send_task(self, name: str, args: list[str]) -> object: ...


F = TypeVar("F", bound=Callable[..., Any])


def task_wrapper(*args: Any, **kwargs: Any) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        return cast(F, celery.task(*args, **kwargs)(func))

    return decorator


celery = Celery("greenlit", broker=settings.redis_url, backend=settings.redis_url)
celery_runtime = cast(CeleryRuntime, celery)
celery_runtime.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=False,
    broker_transport_options={"visibility_timeout": 3600},
    result_expires=3600,
)


@task_wrapper()
def pulse() -> dict[str, str]:
    return {"status": "worker-ready"}


@task_wrapper(
    bind=True,
    name="app.worker.execute_eval_run",
    acks_late=True,
    reject_on_worker_lost=True,
)
def execute_eval_run(self: CeleryTaskContext, run_id: str) -> dict[str, Any]:
    from app.services.run_engine import execute_eval_run_async

    task_id = self.request.id or str(uuid4())
    return asyncio.run(execute_eval_run_async(run_id, task_id=task_id))


def enqueue_eval_run(run_id: str) -> None:
    celery_runtime.send_task("app.worker.execute_eval_run", args=[run_id])
