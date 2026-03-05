"""Stripe integration for subscription billing.

Handles customer creation, subscription management, and webhook processing.
Requires STRIPE_SECRET_KEY to be configured.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Plan, Subscription, SubscriptionStatus, Tenant

logger = structlog.stdlib.get_logger()


def _get_stripe():
    """Lazy-import stripe to avoid import errors when not configured."""
    if not settings.stripe_configured:
        raise RuntimeError("Stripe is not configured. Set STRIPE_SECRET_KEY.")
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


async def create_customer(tenant: Tenant, email: str, db: AsyncSession) -> str:
    """Create a Stripe customer for a tenant."""
    stripe = _get_stripe()

    customer = stripe.Customer.create(
        email=email,
        name=tenant.name,
        metadata={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
    )

    logger.info("stripe_customer_created", tenant_id=str(tenant.id), customer_id=customer.id)
    return customer.id


async def create_subscription(
    tenant_id: uuid.UUID,
    plan_id: uuid.UUID,
    stripe_customer_id: str,
    db: AsyncSession,
) -> Subscription:
    """Create a subscription for a tenant."""
    stripe = _get_stripe()

    # Load plan
    plan_result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = plan_result.scalar_one_or_none()
    if not plan or not plan.stripe_price_id:
        raise ValueError("Invalid plan or plan has no Stripe price ID")

    # Create Stripe subscription
    stripe_sub = stripe.Subscription.create(
        customer=stripe_customer_id,
        items=[{"price": plan.stripe_price_id}],
        metadata={"tenant_id": str(tenant_id)},
    )

    subscription = Subscription(
        tenant_id=tenant_id,
        plan_id=plan_id,
        stripe_subscription_id=stripe_sub.id,
        stripe_customer_id=stripe_customer_id,
        status=SubscriptionStatus.ACTIVE,
        current_period_start=datetime.fromtimestamp(stripe_sub.current_period_start, tz=UTC),
        current_period_end=datetime.fromtimestamp(stripe_sub.current_period_end, tz=UTC),
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)

    logger.info("subscription_created", tenant_id=str(tenant_id), subscription_id=stripe_sub.id)
    return subscription


async def cancel_subscription(tenant_id: uuid.UUID, db: AsyncSession) -> Subscription | None:
    """Cancel a tenant's subscription at period end."""
    result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription or not subscription.stripe_subscription_id:
        return None

    stripe = _get_stripe()
    stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        cancel_at_period_end=True,
    )

    subscription.cancel_at = subscription.current_period_end
    await db.commit()
    await db.refresh(subscription)

    logger.info("subscription_cancelled", tenant_id=str(tenant_id))
    return subscription


async def get_billing_portal_url(stripe_customer_id: str, return_url: str) -> str:
    """Generate a Stripe billing portal session URL."""
    stripe = _get_stripe()
    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=return_url,
    )
    return session.url


async def handle_webhook_event(event_type: str, event_data: dict, db: AsyncSession) -> None:
    """Process a Stripe webhook event."""
    handlers = {
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "invoice.paid": _handle_invoice_paid,
        "invoice.payment_failed": _handle_payment_failed,
    }

    handler = handlers.get(event_type)
    if handler:
        await handler(event_data, db)
    else:
        logger.debug("stripe_webhook_unhandled", event_type=event_type)


async def _handle_subscription_updated(data: dict, db: AsyncSession) -> None:
    """Handle subscription status changes."""
    stripe_sub_id = data["object"]["id"]
    status = data["object"]["status"]

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        logger.warning("stripe_subscription_not_found", stripe_sub_id=stripe_sub_id)
        return

    status_map = {
        "active": SubscriptionStatus.ACTIVE,
        "past_due": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELED,
        "trialing": SubscriptionStatus.TRIALING,
        "incomplete": SubscriptionStatus.INCOMPLETE,
    }

    new_status = status_map.get(status)
    if new_status:
        subscription.status = new_status

    obj = data["object"]
    if "current_period_start" in obj:
        subscription.current_period_start = datetime.fromtimestamp(obj["current_period_start"], tz=UTC)
    if "current_period_end" in obj:
        subscription.current_period_end = datetime.fromtimestamp(obj["current_period_end"], tz=UTC)

    await db.commit()
    logger.info("subscription_updated", stripe_sub_id=stripe_sub_id, status=status)


async def _handle_subscription_deleted(data: dict, db: AsyncSession) -> None:
    """Handle subscription cancellation."""
    stripe_sub_id = data["object"]["id"]

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        subscription.status = SubscriptionStatus.CANCELED
        # Downgrade tenant to free plan
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == subscription.tenant_id))
        tenant = tenant_result.scalar_one_or_none()
        if tenant:
            tenant.plan = "free"
        await db.commit()
        logger.info("subscription_deleted", stripe_sub_id=stripe_sub_id)


async def _handle_invoice_paid(data: dict, db: AsyncSession) -> None:
    """Handle successful payment."""
    logger.info("invoice_paid", invoice_id=data["object"]["id"])


async def _handle_payment_failed(data: dict, db: AsyncSession) -> None:
    """Handle failed payment."""
    logger.warning("payment_failed", invoice_id=data["object"]["id"])
