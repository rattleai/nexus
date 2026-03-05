"""Celery tasks — background job processing and webhook delivery."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.workers.celery_app import celery

logger = structlog.stdlib.get_logger()

# Sync engine for Celery workers (asyncpg → psycopg2)
_sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_url, pool_size=3, max_overflow=5, pool_pre_ping=True)
_SyncSession = sessionmaker(_sync_engine)


@celery.task(name="app.workers.ping")
def ping() -> str:
    return "pong"


@celery.task(name="app.workers.process_job", bind=True, max_retries=3)
def process_job(self, job_id: str) -> dict:
    """Process a job. Override this with your domain-specific logic."""
    from app.db.models import Job, JobStatus

    with _SyncSession() as db:
        job = db.execute(select(Job).where(Job.id == uuid.UUID(job_id))).scalar_one_or_none()
        if not job:
            logger.error("job_not_found", job_id=job_id)
            return {"status": "error", "detail": "Job not found"}

        # Mark as processing
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now(UTC)
        db.commit()

        try:
            # ── YOUR DOMAIN LOGIC HERE ──
            # Replace this block with actual processing logic.
            # Access job.type to determine what to do.
            # Access job.result for input payload.
            result = {"message": f"Job {job.type} processed successfully"}
            # ── END DOMAIN LOGIC ──

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(UTC)
            job.result = result
            db.commit()

            logger.info("job_completed", job_id=job_id, type=job.type)

            # Fire webhook if configured
            if job.webhook_url:
                deliver_webhook.delay(
                    job.webhook_url,
                    {
                        "event": "job.completed",
                        "job_id": job_id,
                        "type": job.type,
                        "status": "completed",
                        "result": result,
                    },
                )

            return {"status": "completed", "job_id": job_id}

        except Exception as exc:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(UTC)
            job.error = str(exc)
            db.commit()
            logger.error("job_failed", job_id=job_id, error=str(exc))

            if job.webhook_url:
                deliver_webhook.delay(
                    job.webhook_url,
                    {
                        "event": "job.failed",
                        "job_id": job_id,
                        "type": job.type,
                        "status": "failed",
                        "error": str(exc),
                    },
                )

            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc


@celery.task(name="app.workers.deliver_webhook", bind=True, max_retries=5)
def deliver_webhook(self, url: str, payload: dict) -> dict:
    """Deliver a webhook with exponential backoff retries."""
    import httpx

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload, headers={"Content-Type": "application/json"})
            response.raise_for_status()
        logger.info("webhook_delivered", url=url, status=response.status_code)
        return {"status": "delivered", "url": url}
    except Exception as exc:
        logger.warning("webhook_delivery_failed", url=url, error=str(exc), attempt=self.request.retries + 1)
        raise self.retry(exc=exc, countdown=2**self.request.retries * 5) from exc
