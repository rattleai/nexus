"""MCP tools for billing and wallet operations."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.wallet import wallet_service
from app.db.models import Plan, Subscription

logger = structlog.stdlib.get_logger()


async def billing_get_wallet_balance(*, tenant: Any, db: AsyncSession) -> dict:
    """Get the current token wallet balance.

    Returns the current balance, lifetime purchased, and lifetime consumed tokens.
    Use this to check if you have enough tokens before making AI completions.
    """
    wallet = await wallet_service._get_or_create_wallet(tenant.id, db)
    balance = await wallet_service.get_balance(tenant.id)
    if balance == 0 and wallet.balance_tokens > 0:
        await wallet_service.initialize_balance(tenant.id, db)
        balance = await wallet_service.get_balance(tenant.id)

    return {
        "balance_tokens": balance,
        "lifetime_purchased": wallet.lifetime_purchased,
        "lifetime_consumed": wallet.lifetime_consumed,
    }


async def billing_list_plans(*, db: AsyncSession) -> list[dict]:
    """List all available subscription plans.

    Returns plan names, tiers, prices, limits, and features.
    """
    result = await db.execute(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price_cents.asc())
    )
    plans = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "tier": p.tier.value if hasattr(p.tier, "value") else str(p.tier),
            "price_cents": p.price_cents,
            "billing_period": p.billing_period,
            "limits": p.limits,
            "features": p.features,
        }
        for p in plans
    ]


async def billing_get_subscription(*, tenant: Any, db: AsyncSession) -> dict:
    """Get the current subscription details.

    Returns the active subscription plan, status, and billing period.
    """
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(Subscription.tenant_id == tenant.id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    sub = result.scalar_one_or_none()

    if not sub:
        return {"status": "none", "plan": None}

    plan_data = None
    if sub.plan:
        plan_data = {
            "id": str(sub.plan.id),
            "name": sub.plan.name,
            "tier": sub.plan.tier.value if hasattr(sub.plan.tier, "value") else str(sub.plan.tier),
        }

    return {
        "id": str(sub.id),
        "status": sub.status.value if hasattr(sub.status, "value") else str(sub.status),
        "plan": plan_data,
        "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
    }
