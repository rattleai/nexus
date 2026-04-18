"""Per-tenant × per-user × per-connector rate limiting (P1.5).

Uses a Redis token bucket keyed on ``(tenant, user, connector_slug)``. When
a provider returns HTTP 429 with ``Retry-After``, a secondary "provider
backoff" bucket is set that short-circuits all users of that connector
for the specified duration — respecting the provider's guidance over our
own token-bucket limits.

Fail-open: if Redis is unavailable the rate limiter allows the call so a
Redis outage doesn't break agent execution. Failures are logged for alerting.
"""

from __future__ import annotations

import time
import uuid

import structlog

from app.config import settings
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

_BUCKET_PREFIX = "connector:rl"
_BACKOFF_PREFIX = "connector:backoff"


class RateLimited(Exception):
    """Raised when the rate limit bucket is exhausted."""

    def __init__(self, retry_after: int, message: str = "rate_limited"):
        super().__init__(message)
        self.retry_after = retry_after


class ConnectorRateLimiter:
    """Token bucket (tenant, user, connector) in Redis."""

    async def check_and_consume(
        self,
        *,
        tenant_id: uuid.UUID,
        connector_slug: str,
        actor_user_id: uuid.UUID | None,
    ) -> None:
        """Consume one token. Raises ``RateLimited`` if the bucket is empty."""
        backoff_retry = await self._get_provider_backoff(tenant_id, connector_slug)
        if backoff_retry > 0:
            raise RateLimited(
                retry_after=backoff_retry,
                message="connector is backed off by provider",
            )

        user_part = str(actor_user_id) if actor_user_id else "system"
        bucket_key = f"{_BUCKET_PREFIX}:{tenant_id}:{user_part}:{connector_slug}"

        capacity = max(1, settings.CONNECTOR_RATE_LIMIT_REQUESTS_PER_MINUTE)
        burst = max(capacity, settings.CONNECTOR_RATE_LIMIT_BURST)
        refill_per_second = capacity / 60.0

        try:
            now = time.time()
            async with redis_pool.pipeline(transaction=True) as pipe:
                await pipe.hgetall(bucket_key)
                raw_result = await pipe.execute()

            state = raw_result[0] if raw_result else {}
            tokens = float(state.get("tokens", burst)) if state else float(burst)
            last = float(state.get("last", now)) if state else now

            elapsed = max(0.0, now - last)
            tokens = min(float(burst), tokens + elapsed * refill_per_second)

            if tokens < 1.0:
                retry_after = max(1, int((1.0 - tokens) / refill_per_second) + 1)
                raise RateLimited(retry_after=retry_after)

            tokens -= 1.0

            await redis_pool.hset(
                bucket_key,
                mapping={"tokens": f"{tokens:.4f}", "last": f"{now:.4f}"},
            )
            # Key TTL = 2× the full-refill window so idle buckets are GC'd
            await redis_pool.expire(bucket_key, 120)
        except RateLimited:
            raise
        except Exception:
            # Fail-open — Redis down shouldn't block tool execution
            logger.debug("connector_rate_limiter_redis_error", exc_info=True)
            return

    async def apply_provider_backoff(
        self,
        *,
        tenant_id: uuid.UUID,
        connector_slug: str,
        retry_after: int,
    ) -> None:
        """Record provider 429 backoff that blocks all users of this connector."""
        key = f"{_BACKOFF_PREFIX}:{tenant_id}:{connector_slug}"
        try:
            await redis_pool.setex(key, max(1, retry_after), str(int(time.time())))
            logger.info(
                "connector_provider_backoff",
                tenant_id=str(tenant_id),
                connector_slug=connector_slug,
                retry_after=retry_after,
            )
        except Exception:
            logger.debug("connector_backoff_redis_error", exc_info=True)

    async def _get_provider_backoff(
        self,
        tenant_id: uuid.UUID,
        connector_slug: str,
    ) -> int:
        """Return seconds remaining in provider backoff, or 0 if none."""
        key = f"{_BACKOFF_PREFIX}:{tenant_id}:{connector_slug}"
        try:
            ttl = await redis_pool.ttl(key)
            return int(ttl) if ttl and ttl > 0 else 0
        except Exception:
            return 0


connector_rate_limiter = ConnectorRateLimiter()
