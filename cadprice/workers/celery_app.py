from celery import Celery

from cadprice.config import settings

celery = Celery("cadprice")

celery.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
)

celery.autodiscover_tasks(["cadprice.workers"])
