from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery = Celery("app")

celery.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=86400,
    # Beat schedule
    beat_schedule={
        "cleanup-expired-jobs": {
            "task": "app.workers.periodic.cleanup_expired_jobs",
            "schedule": crontab(hour=2, minute=0),
        },
        "cleanup-stale-processing": {
            "task": "app.workers.periodic.cleanup_stale_processing",
            "schedule": crontab(minute="*/15"),
        },
        "cache-warmup": {
            "task": "app.workers.periodic.cache_warmup",
            "schedule": crontab(minute="*/30"),
        },
        "storage-usage-report": {
            "task": "app.workers.periodic.storage_usage_report",
            "schedule": crontab(hour=6, minute=0),
        },
    },
    beat_max_loop_interval=60,
)

celery.autodiscover_tasks(["app.workers"])
