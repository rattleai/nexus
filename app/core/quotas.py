"""Tenant-aware quota enforcement system.

Tracks and enforces resource limits per tenant based on their plan.
Uses Redis counters for real-time tracking with periodic DB persistence.

Usage:
    from app.core.quotas import check_quota, QuotaMetric

    @router.post("/jobs", dependencies=[Depends(check_quota(QuotaMetric.API_CALLS))])
    async def create_job(...): ...
"""

import enum
import uuid

import structlog
from fastapi import HTTPException, Request

from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()


class QuotaMetric(enum.StrEnum):
    API_CALLS = "api_calls"
    JOBS_PER_MONTH = "jobs_month"
    STORAGE_BYTES = "storage_bytes"
    USERS = "users"
    API_KEYS = "api_keys"
    FILE_UPLOADS_PER_DAY = "uploads_day"


# Default limits per plan tier — override via Plan.limits JSONB
DEFAULT_PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free": {
        QuotaMetric.API_CALLS: 1000,
        QuotaMetric.JOBS_PER_MONTH: 100,
        QuotaMetric.STORAGE_BYTES: 100 * 1024 * 1024,  # 100 MB
        QuotaMetric.USERS: 3,
        QuotaMetric.API_KEYS: 2,
        QuotaMetric.FILE_UPLOADS_PER_DAY: 50,
    },
    "starter": {
        QuotaMetric.API_CALLS: 10_000,
        QuotaMetric.JOBS_PER_MONTH: 1_000,
        QuotaMetric.STORAGE_BYTES: 1024 * 1024 * 1024,  # 1 GB
        QuotaMetric.USERS: 10,
        QuotaMetric.API_KEYS: 10,
        QuotaMetric.FILE_UPLOADS_PER_DAY: 500,
    },
    "pro": {
        QuotaMetric.API_CALLS: 100_000,
        QuotaMetric.JOBS_PER_MONTH: 10_000,
        QuotaMetric.STORAGE_BYTES: 10 * 1024 * 1024 * 1024,  # 10 GB
        QuotaMetric.USERS: 50,
        QuotaMetric.API_KEYS: 50,
        QuotaMetric.FILE_UPLOADS_PER_DAY: 5_000,
    },
    "enterprise": {
        QuotaMetric.API_CALLS: -1,  # unlimited
        QuotaMetric.JOBS_PER_MONTH: -1,
        QuotaMetric.STORAGE_BYTES: -1,
        QuotaMetric.USERS: -1,
        QuotaMetric.API_KEYS: -1,
        QuotaMetric.FILE_UPLOADS_PER_DAY: -1,
    },
}


def _quota_key(tenant_id: uuid.UUID, metric: QuotaMetric) -> str:
    """Build Redis key for a quota counter."""
    return f"quota:{tenant_id}:{metric.value}"


def get_plan_limit(plan: str, metric: QuotaMetric) -> int:
    """Get the limit for a metric on a given plan. Returns -1 for unlimited."""
    plan_limits = DEFAULT_PLAN_LIMITS.get(plan, DEFAULT_PLAN_LIMITS["free"])
    return plan_limits.get(metric, 0)


async def get_current_usage(tenant_id: uuid.UUID, metric: QuotaMetric) -> int:
    """Get the current usage count for a tenant metric from Redis."""
    try:
        value = await redis_pool.get(_quota_key(tenant_id, metric))
        return int(value) if value else 0
    except Exception:
        logger.warning("quota_read_error", tenant_id=str(tenant_id), metric=metric.value)
        return 0


async def increment_usage(tenant_id: uuid.UUID, metric: QuotaMetric, amount: int = 1) -> int:
    """Increment a usage counter. Returns the new value.

    Only sets TTL when the key is newly created (INCRBY returns the amount),
    preventing the expiry from being pushed forward on every call.
    """
    key = _quota_key(tenant_id, metric)
    try:
        new_value = await redis_pool.incrby(key, amount)
        # Only set TTL when the key was just created (value equals the increment)
        if new_value == amount:
            ttl = 86400 if "day" in metric.value else 2592000  # 24h or 30d
            await redis_pool.expire(key, ttl)
        return new_value
    except Exception:
        logger.warning("quota_increment_error", tenant_id=str(tenant_id), metric=metric.value)
        return 0


# Lua script for atomic decrement-and-floor-at-zero
_DECR_FLOOR_SCRIPT = """
local val = redis.call('decrby', KEYS[1], ARGV[1])
if val < 0 then
    redis.call('set', KEYS[1], 0)
    return 0
end
return val
"""


async def decrement_usage(tenant_id: uuid.UUID, metric: QuotaMetric, amount: int = 1) -> int:
    """Atomically decrement a usage counter, flooring at zero."""
    key = _quota_key(tenant_id, metric)
    try:
        result = await redis_pool.eval(_DECR_FLOOR_SCRIPT, 1, key, amount)
        return int(result)
    except Exception:
        logger.warning("quota_decrement_error", tenant_id=str(tenant_id), metric=metric.value)
        return 0


class QuotaEnforcer:
    """FastAPI dependency that checks quota before allowing an operation.

    Usage:
        @router.post("/jobs", dependencies=[Depends(QuotaEnforcer(QuotaMetric.JOBS_PER_MONTH))])
    """

    def __init__(self, metric: QuotaMetric):
        self.metric = metric

    async def __call__(self, request: Request) -> None:
        # Get tenant from request state (set by auth middleware)
        tenant = getattr(request.state, "tenant", None)
        if tenant is None:
            # Fail closed — don't skip quota check if tenant context is missing
            raise HTTPException(status_code=401, detail="Authentication required")

        plan = getattr(tenant, "plan", "free")
        limit = get_plan_limit(plan, self.metric)

        # -1 means unlimited
        if limit == -1:
            return

        current = await get_current_usage(tenant.id, self.metric)
        if current >= limit:
            logger.warning(
                "quota_exceeded",
                tenant_id=str(tenant.id),
                metric=self.metric.value,
                current=current,
                limit=limit,
                plan=plan,
            )
            raise HTTPException(
                status_code=429,
                detail=f"Quota exceeded for {self.metric.value}. Current: {current}, Limit: {limit}. "
                f"Upgrade your plan to increase limits.",
                headers={"X-Quota-Limit": str(limit), "X-Quota-Used": str(current)},
            )
