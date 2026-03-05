"""Celery tasks — background job processing and webhook delivery."""

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.workers.celery_app import celery

logger = structlog.stdlib.get_logger()

# Sync engine for Celery workers (asyncpg → psycopg2)
_sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_url, pool_size=3, max_overflow=5, pool_pre_ping=True, pool_recycle=300)
_SyncSession = sessionmaker(_sync_engine)


def _optimistic_update(db, model, record_id: uuid.UUID, expected_version: int, **values) -> bool:
    """Perform an optimistic-locking UPDATE. Returns True if the row was updated."""
    result = db.execute(
        update(model)
        .where(model.id == record_id, model.version == expected_version)
        .values(version=expected_version + 1, **values)
    )
    db.commit()
    return result.rowcount > 0


def _sign_webhook_payload(payload: dict) -> str:
    """Create an HMAC-SHA256 signature for a webhook payload."""
    body = json.dumps(payload, sort_keys=True, default=str)
    return hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()


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

        # Optimistic lock: only transition PENDING → PROCESSING
        if not _optimistic_update(
            db,
            Job,
            job.id,
            job.version,
            status=JobStatus.PROCESSING,
            started_at=datetime.now(UTC),
        ):
            logger.warning("job_version_conflict", job_id=job_id, expected_version=job.version)
            return {"status": "skipped", "detail": "Job was already picked up by another worker"}

        # Re-read after version bump
        db.expire(job)
        db.refresh(job)

        try:
            # ── YOUR DOMAIN LOGIC HERE ──
            # Replace this block with actual processing logic.
            # Access job.type to determine what to do.
            # Access job.payload for input data.
            result = {"message": f"Job {job.type} processed successfully"}
            # ── END DOMAIN LOGIC ──

            _optimistic_update(
                db,
                Job,
                job.id,
                job.version,
                status=JobStatus.COMPLETED,
                completed_at=datetime.now(UTC),
                result=result,
            )

            logger.info("job_completed", job_id=job_id, type=job.type)

            # Fire webhook if configured
            if job.webhook_url:
                webhook_payload = {
                    "event": "job.completed",
                    "job_id": job_id,
                    "type": job.type,
                    "status": "completed",
                    "result": result,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                deliver_webhook.delay(job.webhook_url, webhook_payload)

            return {"status": "completed", "job_id": job_id}

        except Exception as exc:
            _optimistic_update(
                db,
                Job,
                job.id,
                job.version,
                status=JobStatus.FAILED,
                completed_at=datetime.now(UTC),
                error=str(exc),
            )
            logger.error("job_failed", job_id=job_id, error=str(exc))

            if job.webhook_url:
                webhook_payload = {
                    "event": "job.failed",
                    "job_id": job_id,
                    "type": job.type,
                    "status": "failed",
                    "error": str(exc),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                deliver_webhook.delay(job.webhook_url, webhook_payload)

            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc


@celery.task(name="app.workers.deliver_webhook", bind=True, max_retries=5)
def deliver_webhook(self, url: str, payload: dict) -> dict:
    """Deliver a webhook with HMAC-SHA256 signature and exponential backoff retries."""
    import httpx

    signature = _sign_webhook_payload(payload)
    timestamp = str(int(time.time()))

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
        "X-Webhook-Timestamp": timestamp,
    }

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        logger.info("webhook_delivered", url=url, status=response.status_code)
        return {"status": "delivered", "url": url}
    except Exception as exc:
        logger.warning("webhook_delivery_failed", url=url, error=str(exc), attempt=self.request.retries + 1)
        raise self.retry(exc=exc, countdown=2**self.request.retries * 5) from exc
