from celery import Celery

from app.config import settings

celery = Celery("greenlit", broker=settings.redis_url, backend=settings.redis_url)


@celery.task
def pulse() -> dict[str, str]:
    return {"status": "worker-ready"}
