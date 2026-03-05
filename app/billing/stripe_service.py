"""Stripe integration for subscription billing.

Handles customer creation, subscription management, checkout sessions,
and webhook processing with idempotency protection.
Requires STRIPE_SECRET_KEY to be configured.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.email import EmailTemplate, send_email
from app.core.redis import redis_pool
from app.db.models import Plan, Subscription, SubscriptionStatus, Tenant, User

logger = structlog.stdlib.get_logger()

# Redis TTL for webhook idempotency (24 hours)
_WEBHOOK_IDEMPOTENCY_TTL = 86400


def _get_stripe():
    """Lazy-import stripe to avoid import errors when not configured."""
    if not settings.stripe_configured:
        raise RuntimeError("Stripe is not configured. Set STRIPE_SECRET_KEY.")
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


async def _is_event_processed(event_id: str) -> bool:
    """Check if a Stripe webhook event has already been processed (idempotency)."""
    try:
        key = f"stripe_event:{event_id}"
        result = await redis_pool.get(key)
        return result is not None
    except Exception:
        return False


async def _mark_event_processed(event_id: str) -> None:
    """Mark a Stripe webhook event as processed."""
    try:
        key = f"stripe_event:{event_id}"
        await redis_pool.setex(key, _WEBHOOK_IDEMPOTENCY_TTL, "1")
    except Exception:
        logger.warning("stripe_idempotency_mark_failed", event_id=event_id)


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


async def create_checkout_session(
    tenant_id: uuid.UUID,
    plan_id: uuid.UUID,
    return_url: str,
    db: AsyncSession,
) -> str:
    """Create a Stripe Checkout Session for subscribing to a plan.

    Returns the checkout session URL.
    """
    stripe = _get_stripe()

    # Load plan
    plan_result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = plan_result.scalar_one_or_none()
    if not plan or not plan.stripe_price_id:
        raise ValueError("Invalid plan or plan has no Stripe price ID")

    # Load or create Stripe customer
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    subscription = sub_result.scalar_one_or_none()
    customer_id = subscription.stripe_customer_id if subscription else None

    if not customer_id:
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = tenant_result.scalar_one_or_none()
        if not tenant:
            raise ValueError("Tenant not found")

        # Find tenant owner for email
        from app.db.models import TenantMembership, UserRole

        owner_result = await db.execute(
            select(User).join(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.role == UserRole.OWNER,
            )
        )
        owner = owner_result.scalar_one_or_none()
        email = owner.email if owner else f"{tenant.slug}@billing.local"
        customer_id = await create_customer(tenant, email, db)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
        success_url=f"{return_url}?session_id={{CHECKOUT_SESSION_ID}}&status=success",
        cancel_url=f"{return_url}?status=canceled",
        metadata={"tenant_id": str(tenant_id), "plan_id": str(plan_id)},
    )

    logger.info("checkout_session_created", tenant_id=str(tenant_id), plan_id=str(plan_id))
    return session.url


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

    # Update tenant plan
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if tenant:
        tenant.plan = plan.name
        await db.commit()

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


async def handle_webhook_event(
    event_id: str, event_type: str, event_data: dict, db: AsyncSession
) -> None:
    """Process a Stripe webhook event with idempotency protection."""
    # Idempotency check
    if await _is_event_processed(event_id):
        logger.info("stripe_webhook_duplicate", event_id=event_id, event_type=event_type)
        return

    handlers = {
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "invoice.paid": _handle_invoice_paid,
        "invoice.payment_failed": _handle_payment_failed,
        "checkout.session.completed": _handle_checkout_completed,
    }

    handler = handlers.get(event_type)
    if handler:
        await handler(event_data, db)

    await _mark_event_processed(event_id)
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
    """Handle subscription cancellation — downgrade tenant to free."""
    stripe_sub_id = data["object"]["id"]

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return

    subscription.status = SubscriptionStatus.CANCELED
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == subscription.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if tenant:
        tenant.plan = "free"

    await db.commit()

    # Send cancellation email to tenant owner
    await _notify_tenant_owner(
        subscription.tenant_id,
        EmailTemplate.SUBSCRIPTION_CANCELED,
        {"plan_name": "subscription", "billing_url": f"{settings.APP_BASE_URL}/settings/billing"},
        db,
    )

    logger.info("subscription_deleted", stripe_sub_id=stripe_sub_id)


async def _handle_invoice_paid(data: dict, db: AsyncSession) -> None:
    """Handle successful payment — send receipt email."""
    invoice = data["object"]
    customer_id = invoice.get("customer")
    amount_paid = invoice.get("amount_paid", 0)

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == customer_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        logger.info("invoice_paid_no_subscription", invoice_id=invoice["id"])
        return

    # Load plan name
    plan_result = await db.execute(select(Plan).where(Plan.id == subscription.plan_id))
    plan = plan_result.scalar_one_or_none()
    plan_name = plan.name if plan else "subscription"

    amount_str = f"${amount_paid / 100:.2f}"
    await _notify_tenant_owner(
        subscription.tenant_id,
        EmailTemplate.PAYMENT_RECEIVED,
        {"amount": amount_str, "plan_name": plan_name},
        db,
    )

    logger.info("invoice_paid", invoice_id=invoice["id"], amount=amount_paid)


async def _handle_payment_failed(data: dict, db: AsyncSession) -> None:
    """Handle failed payment — send dunning email."""
    invoice = data["object"]
    customer_id = invoice.get("customer")

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == customer_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return

    # Update status to past_due
    subscription.status = SubscriptionStatus.PAST_DUE
    await db.commit()

    plan_result = await db.execute(select(Plan).where(Plan.id == subscription.plan_id))
    plan = plan_result.scalar_one_or_none()
    plan_name = plan.name if plan else "subscription"

    await _notify_tenant_owner(
        subscription.tenant_id,
        EmailTemplate.PAYMENT_FAILED,
        {"plan_name": plan_name, "billing_url": f"{settings.APP_BASE_URL}/settings/billing"},
        db,
    )

    logger.warning("payment_failed", invoice_id=invoice["id"])


async def _handle_checkout_completed(data: dict, db: AsyncSession) -> None:
    """Handle checkout session completion — create subscription record."""
    session = data["object"]
    tenant_id_str = session.get("metadata", {}).get("tenant_id")
    plan_id_str = session.get("metadata", {}).get("plan_id")
    stripe_sub_id = session.get("subscription")
    customer_id = session.get("customer")

    if not all([tenant_id_str, plan_id_str, stripe_sub_id, customer_id]):
        logger.warning("checkout_incomplete_metadata", session_id=session["id"])
        return

    tenant_id = uuid.UUID(tenant_id_str)
    plan_id = uuid.UUID(plan_id_str)

    # Check if subscription already exists
    existing = await db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    subscription = existing.scalar_one_or_none()

    # Load Stripe subscription for period info
    stripe = _get_stripe()
    stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)

    if subscription:
        # Update existing
        subscription.plan_id = plan_id
        subscription.stripe_subscription_id = stripe_sub_id
        subscription.stripe_customer_id = customer_id
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.current_period_start = datetime.fromtimestamp(stripe_sub.current_period_start, tz=UTC)
        subscription.current_period_end = datetime.fromtimestamp(stripe_sub.current_period_end, tz=UTC)
        subscription.cancel_at = None
    else:
        # Create new
        subscription = Subscription(
            tenant_id=tenant_id,
            plan_id=plan_id,
            stripe_subscription_id=stripe_sub_id,
            stripe_customer_id=customer_id,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=datetime.fromtimestamp(stripe_sub.current_period_start, tz=UTC),
            current_period_end=datetime.fromtimestamp(stripe_sub.current_period_end, tz=UTC),
        )
        db.add(subscription)

    # Update tenant plan
    plan_result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = plan_result.scalar_one_or_none()
    if plan:
        tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = tenant_result.scalar_one_or_none()
        if tenant:
            tenant.plan = plan.name

    await db.commit()
    logger.info("checkout_completed", tenant_id=tenant_id_str, plan_id=plan_id_str)


async def _notify_tenant_owner(
    tenant_id: uuid.UUID,
    template: EmailTemplate,
    context: dict,
    db: AsyncSession,
) -> None:
    """Send an email to the tenant owner."""
    from app.db.models import TenantMembership, UserRole

    owner_result = await db.execute(
        select(User).join(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.role == UserRole.OWNER,
        )
    )
    owner = owner_result.scalar_one_or_none()
    if owner:
        ctx = {**context, "display_name": owner.display_name or owner.email}
        await send_email(to=owner.email, template=template, context=ctx)
