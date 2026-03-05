"""Periodic Celery tasks — scheduled via Beat.

These tasks handle automated housekeeping: cleanup, cache warming, and usage reporting.
"""

import json
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, select, update

from app.config import settings
from app.workers.celery_app import celery
from app.workers.tasks import _SyncSession

logger = structlog.stdlib.get_logger()


@celery.task(name="app.workers.periodic.cleanup_expired_jobs")
def cleanup_expired_jobs() -> dict:
    """Hard-delete soft-deleted jobs older than 30 days."""
    from app.db.models import Job

    cutoff = datetime.now(UTC) - timedelta(days=30)
    with _SyncSession() as db:
        result = db.execute(
            delete(Job).where(Job.deleted_at.isnot(None), Job.deleted_at < cutoff)
        )
        count = result.rowcount
        db.commit()

    logger.info("cleanup_expired_jobs_completed", deleted_count=count, cutoff=cutoff.isoformat())
    return {"deleted": count, "cutoff": cutoff.isoformat()}


@celery.task(name="app.workers.periodic.cleanup_stale_processing")
def cleanup_stale_processing() -> dict:
    """Mark jobs stuck in PROCESSING for >1 hour as FAILED."""
    from app.db.models import Job, JobStatus

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    with _SyncSession() as db:
        result = db.execute(
            update(Job)
            .where(
                Job.status == JobStatus.PROCESSING,
                Job.started_at < cutoff,
                Job.deleted_at.is_(None),
            )
            .values(
                status=JobStatus.FAILED,
                error="Timed out: stuck in PROCESSING for over 1 hour",
                completed_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session=False)
        )
        count = result.rowcount
        db.commit()

    if count > 0:
        logger.warning("cleanup_stale_processing_completed", failed_count=count)
    else:
        logger.info("cleanup_stale_processing_completed", failed_count=0)
    return {"failed": count}


@celery.task(name="app.workers.periodic.cache_warmup")
def cache_warmup() -> dict:
    """Pre-warm cache for active tenants."""
    import redis as sync_redis

    from app.db.models import Tenant

    with _SyncSession() as db:
        tenants = (
            db.execute(select(Tenant).where(Tenant.is_active.is_(True), Tenant.deleted_at.is_(None)))
            .scalars()
            .all()
        )

    r = sync_redis.from_url(settings.REDIS_URL)
    warmed = 0
    try:
        for t in tenants:
            key = f"cache:tenants:{t.id}"
            data = json.dumps(
                {
                    "id": str(t.id),
                    "name": t.name,
                    "slug": t.slug,
                    "plan": t.plan,
                    "is_active": t.is_active,
                },
                default=str,
            )
            r.setex(key, 600, data)
            warmed += 1
    finally:
        r.close()

    logger.info("cache_warmup_completed", tenants_warmed=warmed)
    return {"warmed": warmed}


@celery.task(name="app.workers.periodic.storage_usage_report")
def storage_usage_report() -> dict:
    """Log storage usage per tenant (daily)."""
    from app.db.models import Job, Tenant

    with _SyncSession() as db:
        results = db.execute(
            select(
                Tenant.id,
                Tenant.slug,
                Tenant.plan,
                func.count(Job.id).label("job_count"),
            )
            .join(Job, Job.tenant_id == Tenant.id, isouter=True)
            .where(Tenant.deleted_at.is_(None))
            .group_by(Tenant.id, Tenant.slug, Tenant.plan)
        ).all()

    report = []
    for row in results:
        entry = {
            "tenant_id": str(row[0]),
            "slug": row[1],
            "plan": row[2],
            "job_count": row[3],
        }
        report.append(entry)
        logger.info("storage_usage", **entry)

    logger.info("storage_usage_report_completed", tenant_count=len(report))
    return {"tenants": len(report), "report": report}
