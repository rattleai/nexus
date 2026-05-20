import json

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
    task_time_limit=600,  # Hard kill after 10 minutes
    task_soft_time_limit=540,  # Raise SoftTimeLimitExceeded after 9 minutes
    task_reject_on_worker_lost=True,  # Re-queue tasks when worker is force-killed
    # Broker connection resilience — auto-reconnect on Redis restarts
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    broker_connection_timeout=10,
    broker_transport_options={
        "visibility_timeout": 43200,  # 12h — prevents premature re-delivery of long-running tasks
    },
    # Task routing — separate queues for isolation
    task_routes={
        "app.agents.*": {"queue": "agents"},
        "app.billing.*": {"queue": "billing"},
    },
    task_default_queue="default",
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
        "cleanup-stale-agent-instances": {
            "task": "app.agents.tasks.cleanup_stale_instances",
            "schedule": crontab(minute="*/5"),
        },
        "hard-purge-deleted-accounts": {
            "task": "app.workers.periodic.hard_purge_deleted_accounts",
            "schedule": crontab(hour=4, minute=0),
        },
        "hard-purge-deleted-users": {
            "task": "app.workers.periodic.hard_purge_deleted_users",
            "schedule": crontab(hour=4, minute=30),
        },
        "enforce-data-retention": {
            "task": "app.workers.periodic.enforce_data_retention",
            "schedule": crontab(hour=5, minute=0),
        },
    },
    beat_max_loop_interval=60,
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=settings.REDIS_URL,
)

celery.autodiscover_tasks(["app.workers", "app.agents", "app.docprocessor"])

# autodiscover_tasks only imports each package's ``tasks`` submodule. Beat
# schedules reference tasks in other modules (app.workers.periodic,
# app.workers.event_consumer, app.workers.webhook_delivery, app.agents.tasks,
# app.connectors.tasks) that must also be imported so the worker process
# registers them on the Celery task registry — otherwise beat enqueues
# tasks that workers raise ``Received unregistered task of type`` for.
import app.workers.event_consumer
import app.workers.periodic
import app.workers.webhook_delivery

try:
    import app.agents.tasks
except Exception:  # pragma: no cover — agents module optional
    pass
try:
    import app.connectors.tasks  # noqa: F401
except Exception:  # pragma: no cover — connectors optional
    pass

# ── Plugin task discovery ──────────────────────────────────
from app.plugins.registry import registry as _plugin_registry

for _plugin in _plugin_registry:
    _celery_cfg = _plugin.get_celery_config()
    _extra_discover = _celery_cfg.get("autodiscover", [])
    if _extra_discover:
        celery.autodiscover_tasks(_extra_discover)
    _extra_routes = _celery_cfg.get("task_routes", {})
    if _extra_routes:
        celery.conf.task_routes.update(_extra_routes)
    _extra_beat = _celery_cfg.get("beat_schedule", {})
    if _extra_beat:
        celery.conf.beat_schedule.update(_extra_beat)


# ── Dead Letter Queue: publish failed tasks to Redis Stream ──────────

from celery.signals import task_failure, task_postrun, task_prerun


@task_failure.connect
def _publish_to_dlq(sender=None, task_id=None, exception=None, traceback=None, args=None, kwargs=None, **kw):
    """Publish failed task metadata to a Redis Stream dead letter queue.

    Enables monitoring, alerting, and replay of failed tasks.
    """
    import redis

    try:
        # Redact sensitive fields before DLQ publish
        safe_kwargs = {k: v for k, v in kwargs.items() if k != "api_key_id"} if kwargs else {}
        dlq_entry = {
            "task_id": task_id or "",
            "task_name": sender.name if sender else "unknown",
            "exception_type": type(exception).__name__ if exception else "Unknown",
            "exception_message": str(exception)[:1000] if exception else "",
            "args": json.dumps(args, default=str)[:2000] if args else "[]",
            "kwargs": json.dumps(safe_kwargs, default=str)[:2000] if safe_kwargs else "{}",
        }
        r = redis.from_url(settings.REDIS_URL)
        try:
            r.xadd("dlq:celery", dlq_entry, maxlen=10000)
        finally:
            r.close()
    except Exception:
        import structlog

        structlog.stdlib.get_logger().error(
            "dlq_publish_failed",
            task_id=task_id,
            exc_info=True,
        )


# ── Context propagation: bind request_id/tenant_id to worker logs ──────────


@task_prerun.connect
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


@task_postrun.connect
def _clear_task_context(sender=None, **kw):
    """Clear structlog context after task completes."""
    import structlog

    structlog.contextvars.unbind_contextvars("request_id", "tenant_id", "celery_task_id", "celery_task_name")


# Initialize OpenTelemetry for workers (if enabled)
if settings.OTEL_ENABLED:
    from app.core.telemetry import setup_telemetry

    setup_telemetry(settings.OTEL_SERVICE_NAME)
