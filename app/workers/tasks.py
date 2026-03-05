"""Celery tasks — background job processing and webhook delivery."""

import hashlib
import hmac
import json
import threading
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import urlparse

import structlog
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.workers.celery_app import celery

logger = structlog.stdlib.get_logger()

# Sync engine for Celery workers (uses dedicated sync URL or derived from async URL)
_sync_engine = create_engine(
    settings.sync_database_url, pool_size=3, max_overflow=5, pool_pre_ping=True, pool_recycle=300
)
_SyncSession = sessionmaker(_sync_engine)


# ── Circuit Breaker ──────────────────────────────────────────────────────────


class CircuitBreaker:
    """Per-host circuit breaker for webhook delivery.

    Uses Redis for shared state across Celery workers, with an in-memory
    fallback when Redis is unavailable.

    States:
      - CLOSED: normal operation, requests pass through.
      - OPEN: too many recent failures, requests are rejected immediately.
      - HALF_OPEN: after a cooldown, allow one probe request.
    """

    FAILURE_THRESHOLD = 5
    RECOVERY_TIMEOUT = 300  # seconds before trying again

    def __init__(self) -> None:
        # In-memory fallback (used when Redis is unavailable)
        self._failures: dict[str, int] = defaultdict(int)
        self._last_failure_time: dict[str, float] = {}
        self._lock = threading.Lock()
        self._redis = None
        self._redis_init_lock = threading.Lock()

    def _get_redis(self):
        """Lazy-init a sync Redis client. Returns None if unavailable."""
        if self._redis is None:
            with self._redis_init_lock:
                if self._redis is None:
                    try:
                        import redis as sync_redis
                        self._redis = sync_redis.from_url(
                            settings.REDIS_URL,
                            socket_connect_timeout=2,
                            socket_timeout=2,
                        )
                        self._redis.ping()
                    except Exception:
                        logger.warning("circuit_breaker_redis_unavailable_using_memory_fallback")
                        self._redis = None
        return self._redis

    def _host_key(self, url: str) -> str:
        return urlparse(url).netloc

    def _redis_failures_key(self, host: str) -> str:
        return f"cb:webhook:{host}:failures"

    def _redis_last_fail_key(self, host: str) -> str:
        return f"cb:webhook:{host}:last_fail"

    def is_open(self, url: str) -> bool:
        """Return True if the circuit is open (should NOT attempt delivery)."""
        host = self._host_key(url)
        r = self._get_redis()

        if r is not None:
            try:
                failures = int(r.get(self._redis_failures_key(host)) or 0)
                if failures < self.FAILURE_THRESHOLD:
                    return False
                last_fail = float(r.get(self._redis_last_fail_key(host)) or 0)
                if time.time() - last_fail > self.RECOVERY_TIMEOUT:
                    return False
                return True
            except Exception:
                logger.warning("circuit_breaker_redis_read_error_using_fallback")

        # In-memory fallback
        with self._lock:
            failures = self._failures.get(host, 0)
            if failures < self.FAILURE_THRESHOLD:
                return False
            last_fail = self._last_failure_time.get(host, 0)
            if time.time() - last_fail > self.RECOVERY_TIMEOUT:
                return False
            return True

    def record_success(self, url: str) -> None:
        host = self._host_key(url)
        r = self._get_redis()

        if r is not None:
            try:
                r.delete(self._redis_failures_key(host), self._redis_last_fail_key(host))
                return
            except Exception:
                logger.warning("circuit_breaker_redis_write_error_using_fallback")

        with self._lock:
            self._failures.pop(host, None)
            self._last_failure_time.pop(host, None)

    def record_failure(self, url: str) -> None:
        host = self._host_key(url)
        r = self._get_redis()
        expiry = self.RECOVERY_TIMEOUT * 2

        if r is not None:
            try:
                pipe = r.pipeline()
                pipe.incr(self._redis_failures_key(host))
                pipe.expire(self._redis_failures_key(host), expiry)
                pipe.set(self._redis_last_fail_key(host), str(time.time()), ex=expiry)
                pipe.execute()
                return
            except Exception:
                logger.warning("circuit_breaker_redis_write_error_using_fallback")

        with self._lock:
            self._failures[host] = self._failures.get(host, 0) + 1
            self._last_failure_time[host] = time.time()


_webhook_breaker = CircuitBreaker()


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


def _sign_webhook_payload(payload: dict) -> str:
    """Create an HMAC-SHA256 signature for a webhook payload.

    Uses a dedicated WEBHOOK_SIGNING_KEY to avoid sharing the JWT SECRET_KEY.
    """
    signing_key = settings.WEBHOOK_SIGNING_KEY or settings.SECRET_KEY
    body = json.dumps(payload, sort_keys=True, default=str)
    return hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()


# ── Tasks ────────────────────────────────────────────────────────────────────


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
                _optimistic_update(
                    db,
                    Job,
                    job.id,
                    job.version,
                    status=JobStatus.PENDING,
                )
                db.commit()
                logger.warning("job_retrying", job_id=job_id, attempt=self.request.retries + 1, error=str(exc))
                raise self.retry(exc=exc, countdown=2**self.request.retries) from exc


@celery.task(name="app.workers.deliver_webhook", bind=True, max_retries=5)
def deliver_webhook(self, url: str, payload: dict) -> dict:
    """Deliver a webhook with HMAC-SHA256 signature, circuit breaker, and exponential backoff."""
    import httpx

    # Check circuit breaker before attempting delivery
    if _webhook_breaker.is_open(url):
        logger.warning("webhook_circuit_open", url=url)
        # Don't retry — the circuit is open. It will auto-recover after RECOVERY_TIMEOUT.
        return {"status": "circuit_open", "url": url}

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
        _webhook_breaker.record_success(url)
        logger.info("webhook_delivered", url=url, status=response.status_code)
        return {"status": "delivered", "url": url}
    except Exception as exc:
        _webhook_breaker.record_failure(url)
        logger.warning("webhook_delivery_failed", url=url, error=str(exc), attempt=self.request.retries + 1)
        raise self.retry(exc=exc, countdown=2**self.request.retries * 5) from exc
