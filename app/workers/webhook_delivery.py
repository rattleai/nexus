"""Webhook delivery worker with exponential retry and DLQ.

Guarantees webhook delivery with:
    - Exponential backoff (1s, 2s, 4s, 8s, 16s)
    - HMAC-SHA256 signature for payload verification
    - Dead letter queue after 5 failed attempts
    - Per-endpoint circuit breaking
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx
import structlog
from celery import shared_task

from app.config import settings
from app.core.circuit_breaker import webhook_breaker

logger = structlog.stdlib.get_logger()

_MAX_RETRIES = 5
_DELIVERY_TIMEOUT = 10  # seconds


def _sign_payload(payload: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for webhook payload verification."""
    return hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


@shared_task(
    bind=True,
    max_retries=_MAX_RETRIES,
    default_retry_delay=1,
    acks_late=True,
    queue="default",
)
def deliver_webhook(
    self,
    *,
    webhook_id: str,
    url: str,
    event_type: str,
    payload: dict,
    secret: str = "",
    attempt: int = 1,
) -> dict:
    """Deliver a webhook with retry and HMAC signing.

    On final failure, publishes to the DLQ Redis stream.
    """
    breaker_key = webhook_breaker.host_key(url)

    if webhook_breaker.is_open(breaker_key):
        state = webhook_breaker.get_state(breaker_key)
        logger.warning(
            "webhook_circuit_open",
            webhook_id=webhook_id,
            url=url,
            retry_after=state.get("retry_after_seconds"),
        )
        # Retry after circuit recovery timeout
        raise self.retry(
            countdown=state.get("retry_after_seconds", 60),
            exc=Exception("Circuit breaker open"),
        )

    payload_bytes = json.dumps(payload, default=str).encode("utf-8")
    timestamp = str(int(time.time()))

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Event": event_type,
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Delivery": webhook_id,
    }

    if secret:
        signature = _sign_payload(
            f"{timestamp}.".encode() + payload_bytes,
            secret,
        )
        headers["X-Webhook-Signature"] = f"sha256={signature}"

    try:
        with httpx.Client(timeout=_DELIVERY_TIMEOUT) as client:
            response = client.post(url, content=payload_bytes, headers=headers)

        if response.status_code < 300:
            webhook_breaker.record_success(breaker_key)
            logger.info(
                "webhook_delivered",
                webhook_id=webhook_id,
                status_code=response.status_code,
                attempt=attempt,
            )
            return {
                "status": "delivered",
                "status_code": response.status_code,
                "attempt": attempt,
            }

        webhook_breaker.record_failure(breaker_key)
        error_msg = f"HTTP {response.status_code}"

    except Exception as exc:
        webhook_breaker.record_failure(breaker_key)
        error_msg = str(exc)

    logger.warning(
        "webhook_delivery_failed",
        webhook_id=webhook_id,
        url=url,
        attempt=attempt,
        error=error_msg,
    )

    if attempt >= _MAX_RETRIES:
        # Publish to DLQ after final failure
        _publish_to_dlq(webhook_id, url, event_type, payload, error_msg, attempt)
        return {"status": "failed", "error": error_msg, "attempt": attempt}

    # Exponential backoff: 1s, 2s, 4s, 8s, 16s
    backoff = 2 ** (attempt - 1)
    raise self.retry(countdown=backoff, exc=Exception(error_msg))


def _publish_to_dlq(
    webhook_id: str,
    url: str,
    event_type: str,
    payload: dict,
    error: str,
    attempts: int,
) -> None:
    """Publish failed webhook to Redis Stream DLQ."""
    try:
        import redis

        r = redis.from_url(settings.REDIS_URL)
        r.xadd(
            "dlq:webhooks",
            {
                "webhook_id": webhook_id,
                "url": url,
                "event_type": event_type,
                "payload": json.dumps(payload, default=str)[:5000],
                "error": error[:500],
                "attempts": str(attempts),
            },
            maxlen=10000,
        )
    except Exception:
        logger.error("webhook_dlq_publish_failed", webhook_id=webhook_id, exc_info=True)
