"""FastAPI dependencies for AI endpoints.

Provides reusable dependency injection for wallet balance checks,
AI feature gate, and quota enforcement.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.wallet import InsufficientBalanceError, wallet_service
from app.api.deps import get_current_tenant, get_db
from app.config import settings
from app.core.quotas import QuotaMetric, get_current_usage, get_plan_limit
from app.db.models.core import Tenant

logger = structlog.stdlib.get_logger()


async def require_ai_enabled() -> None:
    """Dependency that checks if the AI gateway is enabled globally."""
    if not settings.AI_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="AI gateway is not enabled on this platform.",
        )


class RequireWalletBalance:
    """FastAPI dependency that ensures the tenant has a positive wallet balance.

    Usage:
        @router.post("/completions", dependencies=[Depends(RequireWalletBalance())])
    """

    async def __call__(
        self,
        request: Request,
        tenant: Tenant = Depends(get_current_tenant),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        # Initialize wallet in Redis if needed
        balance = await wallet_service.get_balance(tenant.id)
        if balance <= 0:
            # Try loading from DB
            await wallet_service.initialize_balance(tenant.id, db)
            balance = await wallet_service.get_balance(tenant.id)

        if balance <= 0:
            raise HTTPException(
                status_code=402,
                detail="Insufficient token balance. Please top up your wallet.",
                headers={"X-Wallet-Balance": str(balance)},
            )

        # Store balance on request state for downstream use
        request.state.wallet_balance = balance


class AIQuotaEnforcer:
    """FastAPI dependency that checks AI-specific quotas.

    Checks both ai_requests_day and ai_tokens_month limits.

    Usage:
        @router.post("/completions", dependencies=[Depends(AIQuotaEnforcer())])
    """

    async def __call__(
        self,
        request: Request,
        tenant: Tenant = Depends(get_current_tenant),
    ) -> None:
        plan = getattr(tenant, "plan", "free")

        # Check daily request quota
        req_limit = get_plan_limit(plan, QuotaMetric.AI_REQUESTS_DAY)
        if req_limit != -1:
            try:
                current_requests = await get_current_usage(
                    tenant.id, QuotaMetric.AI_REQUESTS_DAY, fail_open=False
                )
            except Exception:
                raise HTTPException(
                    status_code=503,
                    detail="Quota service temporarily unavailable. Please retry.",
                ) from None

            if current_requests >= req_limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Daily AI request quota exceeded ({current_requests}/{req_limit}). "
                    f"Upgrade your plan for higher limits.",
                    headers={
                        "X-Quota-Limit": str(req_limit),
                        "X-Quota-Used": str(current_requests),
                        "Retry-After": "3600",
                    },
                )

        # Check monthly token quota
        token_limit = get_plan_limit(plan, QuotaMetric.AI_TOKENS_MONTH)
        if token_limit != -1:
            try:
                current_tokens = await get_current_usage(
                    tenant.id, QuotaMetric.AI_TOKENS_MONTH, fail_open=False
                )
            except Exception:
                raise HTTPException(
                    status_code=503,
                    detail="Quota service temporarily unavailable. Please retry.",
                ) from None

            if current_tokens >= token_limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Monthly AI token quota exceeded ({current_tokens}/{token_limit}). "
                    f"Upgrade your plan for higher limits.",
                    headers={
                        "X-Quota-Limit": str(token_limit),
                        "X-Quota-Used": str(current_tokens),
                        "Retry-After": "86400",
                    },
                )
