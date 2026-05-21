"""Plan enforcement middleware — checks tenant plan limits before operations."""

import uuid

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.quotas import QuotaMetric, get_current_usage, get_plan_limit
from app.db.models import Subscription, Tenant

logger = structlog.stdlib.get_logger()


async def get_effective_plan(tenant_id: uuid.UUID, db: AsyncSession) -> str:
    """Get the effective plan for a tenant, considering subscription status."""
    result = await db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id))
    subscription = result.scalar_one_or_none()

    if subscription and subscription.status.value in ("active", "trialing"):
        # Load the plan name
        from app.db.models import Plan

        plan_result = await db.execute(select(Plan).where(Plan.id == subscription.plan_id))
        plan = plan_result.scalar_one_or_none()
        if plan:
            return plan.name

    # Default to tenant's plan field or free
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    return tenant.plan if tenant else "free"


async def enforce_plan_limit(
    tenant_id: uuid.UUID,
    plan: str,
    metric: QuotaMetric,
    current_value: int | None = None,
) -> None:
    """Check if a tenant operation is within plan limits.

    Raises HTTPException 429 if the limit is exceeded.
    """
    limit = get_plan_limit(plan, metric)

    # -1 means unlimited
    if limit == -1:
        return

    if current_value is None:
        current_value = await get_current_usage(tenant_id, metric)

    if current_value >= limit:
        logger.warning(
            "plan_limit_exceeded",
            tenant_id=str(tenant_id),
            plan=plan,
            metric=metric.value,
            current=current_value,
            limit=limit,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": "plan_limit_exceeded",
                "metric": metric.value,
                "current": current_value,
                "limit": limit,
                "plan": plan,
                "message": f"Your {plan} plan allows {limit} {metric.value}. Upgrade your plan to increase this limit.",
            },
        )
