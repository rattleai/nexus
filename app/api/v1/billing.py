"""Billing endpoints — subscription management and Stripe webhooks."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import RequireRole, RequireScopes, get_current_tenant, get_current_user_from_token, get_db
from app.api.rate_limit import RateLimiter
from app.config import settings
from app.core.audit import AuditAction, emit_audit_event
from app.db.models import Plan, Subscription, Tenant, User

router = APIRouter(prefix="/billing")
logger = structlog.stdlib.get_logger()


# ── Schemas ──────────────────────────────────────────────


class PlanResponse(BaseModel):
    id: uuid.UUID
    name: str
    tier: str
    price_cents: int
    billing_period: str
    limits: dict
    features: list

    model_config = {"from_attributes": True}


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    plan: PlanResponse | None = None
    status: str
    current_period_start: object | None
    current_period_end: object | None
    cancel_at: object | None

    model_config = {"from_attributes": True}


class CreateCheckoutRequest(BaseModel):
    plan_id: uuid.UUID
    return_url: str

    @field_validator("return_url")
    @classmethod
    def validate_return_url(cls, v: str) -> str:
        if not v.startswith(settings.APP_BASE_URL):
            raise ValueError("return_url must be on the application domain")
        return v


class BillingPortalRequest(BaseModel):
    return_url: str

    @field_validator("return_url")
    @classmethod
    def validate_return_url(cls, v: str) -> str:
        if not v.startswith(settings.APP_BASE_URL):
            raise ValueError("return_url must be on the application domain")
        return v


class CheckoutResponse(BaseModel):
    url: str


# ── Plan endpoints ───────────────────────────────────────


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(db: AsyncSession = Depends(get_db)):
    """List all available subscription plans."""
    result = await db.execute(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price_cents.asc())
    )
    return result.scalars().all()


# ── Subscription endpoints ───────────────────────────────


@router.get(
    "/subscription",
    response_model=SubscriptionResponse | None,
    dependencies=[Depends(RequireScopes("billing:read"))],
)
async def get_subscription(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get the current tenant's subscription."""
    result = await db.execute(
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .where(Subscription.tenant_id == tenant.id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return None

    return SubscriptionResponse(
        id=subscription.id,
        plan=PlanResponse.model_validate(subscription.plan) if subscription.plan else None,
        status=subscription.status.value,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at=subscription.cancel_at,
    )


@router.post(
    "/subscription/cancel",
    response_model=SubscriptionResponse,
    dependencies=[Depends(RequireRole("owner"))],
)
async def cancel_subscription(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Cancel the current subscription at period end."""
    if not settings.stripe_configured:
        raise HTTPException(status_code=503, detail="Billing not configured")

    from app.billing.stripe_service import cancel_subscription as stripe_cancel

    subscription = await stripe_cancel(user.tenant_id, db)
    if not subscription:
        raise HTTPException(status_code=404, detail="No active subscription")

    await emit_audit_event(
        db,
        action=AuditAction.UPDATE,
        resource_type="subscription",
        resource_id=str(subscription.id),
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
        changes={"action": "cancel"},
    )
    await db.commit()

    # Load plan for response
    plan_result = await db.execute(select(Plan).where(Plan.id == subscription.plan_id))
    plan = plan_result.scalar_one_or_none()

    return SubscriptionResponse(
        id=subscription.id,
        plan=PlanResponse.model_validate(plan) if plan else None,
        status=subscription.status.value,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at=subscription.cancel_at,
    )


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    dependencies=[Depends(RequireRole("owner"))],
)
async def create_checkout(
    body: CreateCheckoutRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for subscribing to a plan."""
    if not settings.stripe_configured:
        raise HTTPException(status_code=503, detail="Billing not configured")

    from app.billing.stripe_service import create_checkout_session

    try:
        url = await create_checkout_session(
            user.tenant_id, body.plan_id, body.return_url, db
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception:
        logger.error("checkout_session_failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Failed to create checkout session") from None

    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="checkout_session",
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
        metadata={"plan_id": str(body.plan_id)},
    )
    await db.commit()

    return CheckoutResponse(url=url)


@router.post("/portal", dependencies=[Depends(RequireRole("owner"))])
async def create_billing_portal(
    body: BillingPortalRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe billing portal session for the tenant."""
    if not settings.stripe_configured:
        raise HTTPException(status_code=503, detail="Billing not configured")

    result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == user.tenant_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription or not subscription.stripe_customer_id:
        raise HTTPException(status_code=404, detail="No billing account found")

    from app.billing.stripe_service import get_billing_portal_url

    url = await get_billing_portal_url(subscription.stripe_customer_id, body.return_url)
    return {"url": url}


# ── Stripe Webhook ───────────────────────────────────────


_webhook_rate_limit = RateLimiter(max_requests=100, window=60, key_prefix="rl:stripe-wh")


@router.post("/webhooks/stripe", dependencies=[Depends(_webhook_rate_limit)])
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle incoming Stripe webhook events."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe webhooks not configured")

    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        import stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        event = stripe.Webhook.construct_event(
            body, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload") from None
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature") from None

    from app.billing.stripe_service import handle_webhook_event

    try:
        await handle_webhook_event(event["id"], event["type"], event["data"], db)
    except Exception:
        # Return 200 to prevent Stripe from retrying permanently on unrecoverable errors.
        # The error is logged for investigation.
        logger.error("stripe_webhook_handler_failed", event_type=event["type"], exc_info=True)
        return {"status": "error", "message": "Event processing failed"}

    logger.info("stripe_webhook_processed", event_type=event["type"])
    return {"status": "ok"}
