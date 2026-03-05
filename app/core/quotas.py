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
    """Increment a usage counter. Returns the new value."""
    key = _quota_key(tenant_id, metric)
    try:
        pipe = redis_pool.pipeline()
        pipe.incrby(key, amount)
        # Set TTL based on metric period (daily or monthly)
        if "day" in metric.value:
            pipe.expire(key, 86400)  # 24 hours
        else:
            pipe.expire(key, 2592000)  # 30 days
        results = await pipe.execute()
        return results[0]
    except Exception:
        logger.warning("quota_increment_error", tenant_id=str(tenant_id), metric=metric.value)
        return 0


async def decrement_usage(tenant_id: uuid.UUID, metric: QuotaMetric, amount: int = 1) -> int:
    """Decrement a usage counter (e.g., when a resource is deleted)."""
    key = _quota_key(tenant_id, metric)
    try:
        result = await redis_pool.decrby(key, amount)
        # Don't let it go negative
        if result < 0:
            await redis_pool.set(key, 0)
            return 0
        return result
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
            # Try to get from the dependency chain via the resolved API key
            return  # Skip quota check if no tenant context (will be caught by auth)

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
