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
from app.core.circuit_breaker import CircuitBreaker
from app.core.circuit_breaker import webhook_breaker as _webhook_breaker
from app.core.metrics import JOB_DURATION, JOBS_TOTAL, WEBHOOK_DELIVERIES_TOTAL
from app.workers.celery_app import celery

logger = structlog.stdlib.get_logger()

# Sync engine for Celery workers (uses dedicated sync URL or derived from async URL)
_sync_engine = create_engine(
    settings.sync_database_url, pool_size=3, max_overflow=5, pool_pre_ping=True, pool_recycle=300
)
_SyncSession = sessionmaker(_sync_engine)


def _admin_sync_url() -> str:
    """Return a psycopg2-compatible URL for the DB superuser connection.

    Derived from ``DATABASE_MIGRATION_URL`` (async dialect) with the
    asyncpg driver stripped. Falls back to the regular sync URL.
    """
    url = settings.DATABASE_MIGRATION_URL or settings.sync_database_url
    return url.replace("+asyncpg", "")


# Admin sync engine — bypasses RLS, for platform sweep tasks only.
_admin_sync_engine = create_engine(
    _admin_sync_url(),
    pool_size=2,
    max_overflow=3,
    pool_pre_ping=True,
    pool_recycle=300,
)
_AdminSyncSession = sessionmaker(_admin_sync_engine)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _optimistic_update(db, model, record_id: uuid.UUID, expected_version: int, **values) -> bool:
    """Perform an optimistic-locking UPDATE. Returns True if the row was updated.

    Note: does NOT commit — caller is responsible for committing.
    """
    result = db.execute(
        update(model)
        .where(model.id == record_id, model.version == expected_version)
        .values(version=expected_version + 1, **values)
    )
    return result.rowcount > 0


def _sign_webhook_payload(payload: dict, timestamp: str, signing_secret: str | None = None) -> str:
    """Create an HMAC-SHA256 signature for a webhook payload.

    The timestamp is included in the signed message to prevent replay attacks.
    Verifiers should reject signatures with timestamps older than a tolerance window.

    Uses the per-endpoint signing secret when available, falling back to
    WEBHOOK_SIGNING_KEY. Never falls back to SECRET_KEY to avoid key reuse.
    """
    signing_key = signing_secret or settings.WEBHOOK_SIGNING_KEY
    if not signing_key:
        raise RuntimeError(
            "No webhook signing key available. Set WEBHOOK_SIGNING_KEY or provide a per-endpoint secret."
        )
    body = json.dumps(payload, sort_keys=True, default=str)
    # Include timestamp in HMAC input so replayed payloads with forged timestamps fail verification
    message = f"{timestamp}.{body}"
    return hmac.new(signing_key.encode(), message.encode(), hashlib.sha256).hexdigest()


# ── Tasks ────────────────────────────────────────────────────────────────────


@celery.task(name="app.workers.ping")
def ping() -> str:
    return "pong"


@celery.task(name="app.workers.process_job", bind=True, max_retries=3, soft_time_limit=300, time_limit=330)
def process_job(self, job_id: str) -> dict:
    """Process a job. Override this with your domain-specific logic."""
    from celery.exceptions import SoftTimeLimitExceeded

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
            db.rollback()
            logger.warning("job_version_conflict", job_id=job_id, expected_version=job.version)
            return {"status": "skipped", "detail": "Job was already picked up by another worker"}

        db.commit()

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

            updated = _optimistic_update(
                db,
                Job,
                job.id,
                job.version,
                status=JobStatus.COMPLETED,
                completed_at=datetime.now(UTC),
                result=result,
            )
            db.commit()

            if not updated:
                logger.warning("job_completion_conflict", job_id=job_id)
                return {"status": "conflict", "detail": "Job was modified concurrently"}

            JOBS_TOTAL.labels(status="completed", type=job.type).inc()
            if job.started_at:
                JOB_DURATION.observe((datetime.now(UTC) - job.started_at).total_seconds())
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

        except SoftTimeLimitExceeded:
            # Graceful timeout — mark job as failed with a clear reason
            _optimistic_update(
                db,
                Job,
                job.id,
                job.version,
                status=JobStatus.FAILED,
                completed_at=datetime.now(UTC),
                error="Job timed out",
            )
            db.commit()
            JOBS_TOTAL.labels(status="timed_out", type=job.type).inc()
            logger.error("job_timed_out", job_id=job_id, type=job.type)

            if job.webhook_url:
                webhook_payload = {
                    "event": "job.failed",
                    "job_id": job_id,
                    "type": job.type,
                    "status": "failed",
                    "error": "Job timed out",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                deliver_webhook.delay(job.webhook_url, webhook_payload)

            return {"status": "timed_out", "job_id": job_id}

        except Exception as exc:
            is_final_attempt = self.request.retries >= self.max_retries

            if is_final_attempt:
                # Only mark as FAILED on final retry
                _optimistic_update(
                    db,
                    Job,
                    job.id,
                    job.version,
                    status=JobStatus.FAILED,
                    completed_at=datetime.now(UTC),
                    error="Processing failed",  # Sanitized error for DB
                )
                db.commit()
                JOBS_TOTAL.labels(status="failed", type=job.type).inc()
                logger.error("job_failed", job_id=job_id, error=str(exc))

                if job.webhook_url:
                    webhook_payload = {
                        "event": "job.failed",
                        "job_id": job_id,
                        "type": job.type,
                        "status": "failed",
                        "error": "Processing failed",  # Sanitized — don't leak internals
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    deliver_webhook.delay(job.webhook_url, webhook_payload)

                return {"status": "failed", "job_id": job_id}
            else:
                # Reset to PENDING for retry
                reset_ok = _optimistic_update(
                    db,
                    Job,
                    job.id,
                    job.version,
                    status=JobStatus.PENDING,
                )
                db.commit()
                if not reset_ok:
                    logger.error("job_retry_reset_conflict", job_id=job_id)
                    return {"status": "conflict", "detail": "Could not reset job for retry"}
                logger.warning("job_retrying", job_id=job_id, attempt=self.request.retries + 1, error=str(exc))
                raise self.retry(exc=exc, countdown=2**self.request.retries) from exc


def _record_webhook_failure(url: str, payload: dict, error: str, attempts: int, endpoint_id: str | None = None) -> None:
    """Record a permanently failed webhook delivery in the DB (dead letter queue).

    This allows operators to investigate and replay failed deliveries.
    """
    from app.db.models import WebhookDelivery

    try:
        with _SyncSession() as db:
            delivery = WebhookDelivery(
                endpoint_id=uuid.UUID(endpoint_id) if endpoint_id else None,
                event=payload.get("event", "unknown"),
                payload=payload,
                status_code=None,
                response_body=error,
                attempts=attempts,
                completed_at=datetime.now(UTC),
            )
            db.add(delivery)
            db.commit()
            logger.info("webhook_failure_recorded", url=url, event=payload.get("event"))
    except Exception:
        logger.error("webhook_failure_record_failed", url=url, exc_info=True)


@celery.task(name="app.workers.deliver_webhook", bind=True, max_retries=5, soft_time_limit=30, time_limit=60)
def deliver_webhook(self, url: str, payload: dict, endpoint_id: str | None = None) -> dict:
    """Deliver a webhook with HMAC-SHA256 signature, circuit breaker, and exponential backoff."""
    import httpx

    from app.core.url_validation import validate_webhook_url

    # Re-validate URL at delivery time to prevent DNS rebinding attacks (TOCTOU)
    ssrf_error = validate_webhook_url(url)
    if ssrf_error:
        logger.warning("webhook_ssrf_blocked", url=url, error=ssrf_error)
        _record_webhook_failure(url, payload, f"SSRF blocked: {ssrf_error}", 1, endpoint_id)
        return {"status": "blocked", "url": url, "reason": ssrf_error}

    # Resolve signing secret at delivery time from the endpoint record,
    # instead of receiving it as a Celery argument (which would store the
    # decrypted secret in plaintext on the Redis broker queue).
    signing_secret = None
    if endpoint_id:
        try:
            from app.db.models import WebhookEndpoint

            with _SyncSession() as db:
                ep = db.execute(
                    select(WebhookEndpoint).where(WebhookEndpoint.id == uuid.UUID(endpoint_id))
                ).scalar_one_or_none()
                if ep:
                    signing_secret = ep.get_secret()
        except Exception:
            logger.warning("webhook_secret_lookup_failed", endpoint_id=endpoint_id)

    host_key = CircuitBreaker.host_key(url)

    # Check circuit breaker before attempting delivery
    if _webhook_breaker.is_open(host_key):
        logger.warning("webhook_circuit_open", url=url)
        if self.request.retries >= self.max_retries:
            _record_webhook_failure(url, payload, "Circuit breaker open", self.request.retries + 1, endpoint_id)
        return {"status": "circuit_open", "url": url}

    timestamp = str(int(time.time()))
    signature = _sign_webhook_payload(payload, timestamp, signing_secret=signing_secret)

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
        "X-Webhook-Timestamp": timestamp,
    }

    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(url, json=payload, headers=headers)
            # Only retry on 5xx server errors and network errors, not 4xx client errors.
            # 4xx indicates a permanent problem (bad request, unauthorized, etc.)
            if response.status_code >= 500:
                response.raise_for_status()
            elif response.status_code >= 400:
                logger.warning(
                    "webhook_client_error",
                    url=url,
                    status=response.status_code,
                    body=response.text[:200],
                )
                _record_webhook_failure(
                    url,
                    payload,
                    f"Client error {response.status_code}",
                    self.request.retries + 1,
                    endpoint_id,
                )
                WEBHOOK_DELIVERIES_TOTAL.labels(status="client_error").inc()
                return {"status": "client_error", "url": url, "code": response.status_code}
        _webhook_breaker.record_success(host_key)
        WEBHOOK_DELIVERIES_TOTAL.labels(status="delivered").inc()
        logger.info("webhook_delivered", url=url, status=response.status_code)
        return {"status": "delivered", "url": url}
    except Exception as exc:
        _webhook_breaker.record_failure(host_key)
        is_final = self.request.retries >= self.max_retries
        logger.warning(
            "webhook_delivery_failed",
            url=url,
            error=str(exc),
            attempt=self.request.retries + 1,
            final=is_final,
        )
        if is_final:
            WEBHOOK_DELIVERIES_TOTAL.labels(status="failed").inc()
            _record_webhook_failure(url, payload, str(exc), self.request.retries + 1, endpoint_id)
        raise self.retry(exc=exc, countdown=2**self.request.retries * 5) from exc
