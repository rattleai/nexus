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
    task_time_limit=600,       # Hard kill after 10 minutes
    task_soft_time_limit=540,  # Raise SoftTimeLimitExceeded after 9 minutes
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
        "cleanup-expired-tokens": {
            "task": "app.workers.periodic.cleanup_expired_tokens",
            "schedule": crontab(hour=3, minute=0),
        },
        "cleanup-expired-invitations": {
            "task": "app.workers.periodic.cleanup_expired_invitations",
            "schedule": crontab(hour=3, minute=30),
        },
    },
    beat_max_loop_interval=60,
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=settings.REDIS_URL,
)

celery.autodiscover_tasks(["app.workers"])


# ── Context propagation: bind request_id/tenant_id to worker logs ──────────


@celery.signals.task_prerun.connect
def _bind_task_context(sender=None, task_id=None, task=None, kwargs=None, **kw):
    """Bind request context (request_id, tenant_id) to structlog for the task."""
    import structlog

    headers = getattr(task.request, "headers", {}) or {}
    ctx = {}
    if headers.get("request_id"):
        ctx["request_id"] = headers["request_id"]
    if headers.get("tenant_id"):
        ctx["tenant_id"] = headers["tenant_id"]
    ctx["celery_task_id"] = task_id
    ctx["celery_task_name"] = task.name
    structlog.contextvars.bind_contextvars(**ctx)


@celery.signals.task_postrun.connect
def _clear_task_context(sender=None, **kw):
    """Clear structlog context after task completes."""
    import structlog

    structlog.contextvars.unbind_contextvars(
        "request_id", "tenant_id", "celery_task_id", "celery_task_name"
    )

# Initialize OpenTelemetry for workers (if enabled)
if settings.OTEL_ENABLED:
    from app.core.telemetry import setup_telemetry

    setup_telemetry(settings.OTEL_SERVICE_NAME)
