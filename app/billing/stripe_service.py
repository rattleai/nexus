"""Stripe integration for subscription billing and credit pack purchases.

Handles customer creation, subscription management, credit pack checkout,
auto-refill setup, and webhook processing with idempotency protection.
Requires STRIPE_SECRET_KEY to be configured.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.email import EmailTemplate, send_email
from app.core.redis import redis_pool
from app.db.models import CreditPack, Plan, Subscription, SubscriptionStatus, Tenant, UsageRecord, User

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


async def _try_claim_event(event_id: str) -> bool:
    """Atomically claim a Stripe webhook event for processing (idempotency).

    Uses SET NX (set-if-not-exists) to prevent TOCTOU races where two
    concurrent webhook deliveries both pass a GET check before either
    marks the event as processed.

    Returns True if this caller claimed the event (should process it).
    Returns False if the event was already claimed (duplicate — skip it).
    """
    try:
        key = f"stripe_event:{event_id}"
        # SET NX returns True only if the key was newly set
        claimed = await redis_pool.set(key, "1", nx=True, ex=_WEBHOOK_IDEMPOTENCY_TTL)
        return bool(claimed)
    except Exception:
        logger.warning("stripe_idempotency_claim_failed", event_id=event_id)
        # On Redis failure, allow processing (fail open) — the handler
        # logic is itself idempotent via DB constraints
        return True


async def create_customer(tenant: Tenant, email: str, db: AsyncSession) -> str:
    """Create a Stripe customer for a tenant."""
    stripe = _get_stripe()

    try:
        customer = stripe.Customer.create(
            email=email,
            name=tenant.name,
            metadata={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
        )
    except stripe.error.StripeError as exc:
        logger.error("stripe_customer_create_failed", tenant_id=str(tenant.id), error=str(exc))
        raise ValueError(f"Failed to create billing customer: {exc}") from exc

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
        automatic_tax={"enabled": True},
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

    # Update tenant plan in the same transaction to maintain atomicity.
    # Previously used two separate commits, risking an inconsistent state
    # where the subscription exists but the tenant plan isn't updated.
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if tenant:
        tenant.plan = plan.name

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


async def create_credit_pack_checkout(
    tenant_id: uuid.UUID,
    pack_id: uuid.UUID,
    return_url: str,
    db: AsyncSession,
) -> str:
    """Create a Stripe Checkout Session for purchasing a credit pack.

    Returns the checkout session URL. Uses mode="payment" (one-time).
    """
    stripe = _get_stripe()

    # Load credit pack
    pack_result = await db.execute(
        select(CreditPack).where(CreditPack.id == pack_id, CreditPack.is_active.is_(True))
    )
    pack = pack_result.scalar_one_or_none()
    if not pack or not pack.stripe_price_id:
        raise ValueError("Invalid credit pack or pack has no Stripe price ID")

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
        mode="payment",
        line_items=[{"price": pack.stripe_price_id, "quantity": 1}],
        success_url=f"{return_url}?session_id={{CHECKOUT_SESSION_ID}}&status=success",
        cancel_url=f"{return_url}?status=canceled",
        metadata={
            "tenant_id": str(tenant_id),
            "type": "credit_pack",
            "pack_id": str(pack_id),
            "amount_usd": str(pack.amount_usd),
        },
        automatic_tax={"enabled": True},
    )

    logger.info("credit_pack_checkout_created", tenant_id=str(tenant_id), pack_id=str(pack_id))
    return session.url


async def create_setup_intent(
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Create a Stripe SetupIntent for saving a card for auto-refill.

    Returns the SetupIntent client secret.
    """
    stripe = _get_stripe()

    # Get Stripe customer ID
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    subscription = sub_result.scalar_one_or_none()
    if not subscription or not subscription.stripe_customer_id:
        raise ValueError("No billing account found. Please set up billing first.")

    setup_intent = stripe.SetupIntent.create(
        customer=subscription.stripe_customer_id,
        payment_method_types=["card"],
        metadata={"tenant_id": str(tenant_id), "type": "auto_refill_setup"},
    )

    logger.info("setup_intent_created", tenant_id=str(tenant_id))
    return setup_intent.client_secret


async def configure_auto_refill(
    tenant_id: uuid.UUID,
    payment_method_id: str,
    threshold_usd: Decimal,
    refill_amount_usd: Decimal,
    db: AsyncSession,
) -> None:
    """Configure auto-refill settings on the tenant's wallet."""
    from app.db.models.ai import DollarWallet

    result = await db.execute(
        select(DollarWallet).where(DollarWallet.tenant_id == tenant_id)
    )
    wallet = result.scalar_one_or_none()
    if not wallet:
        # Create wallet if it doesn't exist
        from app.ai.wallet import wallet_service

        wallet = await wallet_service._get_or_create_wallet(tenant_id, db)

    # Verify the payment method belongs to this tenant's Stripe customer
    sub_result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    subscription = sub_result.scalar_one_or_none()
    if not subscription or not subscription.stripe_customer_id:
        raise ValueError("No billing account found. Please set up billing first.")

    stripe = _get_stripe()
    try:
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        if pm.customer != subscription.stripe_customer_id:
            raise ValueError("Payment method does not belong to this billing account")
    except stripe.error.StripeError as exc:
        raise ValueError(f"Invalid payment method: {exc}") from exc

    wallet.auto_refill_enabled = True
    wallet.auto_refill_threshold_usd = threshold_usd
    wallet.auto_refill_amount_usd = refill_amount_usd
    wallet.stripe_payment_method_id = payment_method_id

    await db.commit()
    logger.info(
        "auto_refill_configured",
        tenant_id=str(tenant_id),
        threshold_usd=str(threshold_usd),
        refill_amount_usd=str(refill_amount_usd),
    )


async def disable_auto_refill(tenant_id: uuid.UUID, db: AsyncSession) -> None:
    """Disable auto-refill for the tenant's wallet."""
    from app.db.models.ai import DollarWallet

    result = await db.execute(
        select(DollarWallet).where(DollarWallet.tenant_id == tenant_id)
    )
    wallet = result.scalar_one_or_none()
    if wallet:
        wallet.auto_refill_enabled = False
        await db.commit()
    logger.info("auto_refill_disabled", tenant_id=str(tenant_id))


async def handle_webhook_event(
    event_id: str, event_type: str, event_data: dict, db: AsyncSession
) -> None:
    """Process a Stripe webhook event with idempotency protection."""
    # Atomic claim: SET NX prevents TOCTOU race on concurrent deliveries
    if not await _try_claim_event(event_id):
        logger.info("stripe_webhook_duplicate", event_id=event_id, event_type=event_type)
        return

    handlers = {
        "customer.subscription.updated": _handle_subscription_updated,
        "customer.subscription.deleted": _handle_subscription_deleted,
        "invoice.paid": _handle_invoice_paid,
        "invoice.payment_failed": _handle_payment_failed,
        "checkout.session.completed": _handle_checkout_completed,
        "payment_intent.succeeded": _handle_payment_intent_succeeded,
    }

    handler = handlers.get(event_type)
    if handler:
        await handler(event_data, db)
    else:
        logger.debug("stripe_webhook_unhandled", event_type=event_type)


def _validate_webhook_tenant(data: dict, subscription: Subscription) -> bool:
    """Cross-check metadata tenant_id against subscription's tenant_id.

    Returns True if valid or no metadata present (backwards-compatible).
    Logs a warning and returns False on mismatch.
    """
    metadata = data.get("object", {}).get("metadata", {})
    meta_tenant_id = metadata.get("tenant_id")
    if meta_tenant_id and str(subscription.tenant_id) != meta_tenant_id:
        logger.error(
            "stripe_webhook_tenant_mismatch",
            expected=str(subscription.tenant_id),
            got=meta_tenant_id,
        )
        return False
    return True


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

    if not _validate_webhook_tenant(data, subscription):
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

    if not _validate_webhook_tenant(data, subscription):
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
    amount_paid = invoice.get("amount_paid") or 0

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == customer_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        logger.info("invoice_paid_no_subscription", invoice_id=invoice["id"])
        return

    if not _validate_webhook_tenant(data, subscription):
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

    if not _validate_webhook_tenant(data, subscription):
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
    """Handle checkout session completion — subscription or credit pack purchase."""
    session = data["object"]
    metadata = session.get("metadata", {})
    checkout_type = metadata.get("type")

    if checkout_type == "credit_pack":
        await _handle_credit_pack_checkout(session, metadata, db)
    else:
        await _handle_subscription_checkout(session, metadata, db)


async def _handle_credit_pack_checkout(
    session: dict, metadata: dict, db: AsyncSession
) -> None:
    """Credit the tenant's wallet after a credit pack purchase."""
    from app.ai.wallet import wallet_service

    tenant_id_str = metadata.get("tenant_id")
    amount_usd_str = metadata.get("amount_usd")
    pack_id_str = metadata.get("pack_id")

    if not tenant_id_str or not amount_usd_str:
        logger.warning("credit_pack_checkout_missing_metadata", session_id=session["id"])
        return

    try:
        tenant_id = uuid.UUID(tenant_id_str)
        amount_usd = Decimal(amount_usd_str)
    except (ValueError, ArithmeticError):
        logger.error("credit_pack_checkout_invalid_metadata", session_id=session["id"])
        return

    # Cross-check metadata amount against the verified payment amount from Stripe.
    # session["amount_total"] is in cents and comes from Stripe's verified payment,
    # not from mutable metadata.
    verified_amount_cents = session.get("amount_total") or 0
    verified_usd = Decimal(verified_amount_cents) / 100
    if verified_usd > 0 and abs(amount_usd - verified_usd) > Decimal("0.01"):
        logger.error(
            "credit_pack_amount_mismatch",
            metadata_amount=str(amount_usd),
            verified_amount=str(verified_usd),
            session_id=session["id"],
        )
        # Use the verified amount from Stripe, not the metadata
        amount_usd = verified_usd

    payment_intent_id = session.get("payment_intent")
    reference_id = f"credit_pack:{session['id']}"

    await wallet_service.topup(
        tenant_id,
        amount_usd,
        reference_id=reference_id,
        stripe_payment_intent_id=payment_intent_id,
        description=f"Credit pack purchase: ${amount_usd}",
        db=db,
    )

    logger.info(
        "credit_pack_checkout_completed",
        tenant_id=tenant_id_str,
        amount_usd=amount_usd_str,
        pack_id=pack_id_str,
    )


async def _handle_subscription_checkout(
    session: dict, metadata: dict, db: AsyncSession
) -> None:
    """Create or update subscription record after subscription checkout."""
    tenant_id_str = metadata.get("tenant_id")
    plan_id_str = metadata.get("plan_id")
    stripe_sub_id = session.get("subscription")
    customer_id = session.get("customer")

    if not all([tenant_id_str, plan_id_str, stripe_sub_id, customer_id]):
        logger.warning("checkout_incomplete_metadata", session_id=session["id"])
        return

    try:
        tenant_id = uuid.UUID(tenant_id_str)
        plan_id = uuid.UUID(plan_id_str)
    except (ValueError, AttributeError):
        logger.error("checkout_invalid_uuid_metadata", session_id=session["id"],
                      tenant_id=tenant_id_str, plan_id=plan_id_str)
        return

    # Check if subscription already exists
    existing = await db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    subscription = existing.scalar_one_or_none()

    # Load Stripe subscription for period info and verify price matches plan
    stripe = _get_stripe()
    try:
        stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
    except Exception as exc:
        logger.error("checkout_stripe_retrieve_failed", stripe_sub_id=stripe_sub_id, error=str(exc))
        raise

    # Verify the Stripe subscription price matches the expected plan price
    plan_result_check = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan_check = plan_result_check.scalar_one_or_none()
    if plan_check and plan_check.stripe_price_id:
        stripe_price_id = stripe_sub.get("items", {}).get("data", [{}])[0].get("price", {}).get("id")
        if stripe_price_id and stripe_price_id != plan_check.stripe_price_id:
            logger.error(
                "checkout_price_mismatch",
                expected_price=plan_check.stripe_price_id,
                actual_price=stripe_price_id,
                session_id=session["id"],
            )
            return

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
    """Send an email to the tenant owner. Fire-and-forget — never fails the caller."""
    try:
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
    except Exception:
        logger.error("notify_tenant_owner_failed", tenant_id=str(tenant_id), exc_info=True)


async def report_usage_to_stripe(
    tenant_id: uuid.UUID,
    metric_name: str,
    quantity: int,
    db: AsyncSession,
) -> bool:
    """Report usage to Stripe's metered billing API.

    Sends a MeterEvent for the given metric. Requires a Stripe Meter
    to be configured in the Stripe dashboard for the metric_name.

    Returns True if the event was sent successfully.
    """
    stripe = _get_stripe()

    # Get customer ID
    result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == tenant_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription or not subscription.stripe_customer_id:
        logger.warning("usage_report_no_customer", tenant_id=str(tenant_id))
        return False

    try:
        stripe.billing.MeterEvent.create(
            event_name=metric_name,
            payload={
                "value": str(quantity),
                "stripe_customer_id": subscription.stripe_customer_id,
            },
            timestamp=int(datetime.now(UTC).timestamp()),
        )
        logger.info(
            "usage_reported_to_stripe",
            tenant_id=str(tenant_id),
            metric=metric_name,
            quantity=quantity,
        )
        return True
    except Exception as exc:
        logger.error(
            "usage_report_failed",
            tenant_id=str(tenant_id),
            metric=metric_name,
            error=str(exc),
        )
        return False


async def get_usage_summary(
    tenant_id: uuid.UUID,
    db: AsyncSession,
    *,
    days: int = 30,
) -> dict:
    """Get usage summary for a tenant over the specified period.

    Aggregates UsageRecord entries by metric type.
    """
    from datetime import timedelta

    from sqlalchemy import func

    cutoff = datetime.now(UTC) - timedelta(days=days)

    result = await db.execute(
        select(
            UsageRecord.metric,
            func.sum(UsageRecord.value).label("total"),
            func.count(UsageRecord.id).label("count"),
        )
        .where(
            UsageRecord.tenant_id == tenant_id,
            UsageRecord.created_at >= cutoff,
        )
        .group_by(UsageRecord.metric)
    )

    metrics = {}
    for row in result.all():
        metrics[row[0]] = {
            "total": float(row[1] or 0),
            "count": row[2] or 0,
        }

    return {
        "tenant_id": str(tenant_id),
        "period_days": days,
        "metrics": metrics,
    }


async def _handle_payment_intent_succeeded(data: dict, db: AsyncSession) -> None:
    """Handle successful PaymentIntent — credit wallet for auto-refill payments."""
    payment_intent = data["object"]
    metadata = payment_intent.get("metadata", {})

    if metadata.get("type") != "auto_refill":
        # Not an auto-refill payment, ignore
        return

    from app.ai.wallet import wallet_service

    tenant_id_str = metadata.get("tenant_id")
    refill_amount_str = metadata.get("refill_amount_usd")

    if not tenant_id_str or not refill_amount_str:
        logger.warning(
            "auto_refill_pi_missing_metadata",
            payment_intent_id=payment_intent["id"],
        )
        return

    try:
        tenant_id = uuid.UUID(tenant_id_str)
        refill_amount = Decimal(refill_amount_str)
    except (ValueError, ArithmeticError):
        logger.error(
            "auto_refill_pi_invalid_metadata",
            payment_intent_id=payment_intent["id"],
        )
        return

    # Enforce a ceiling on auto-refill amount to prevent abuse from
    # tampered PaymentIntent metadata.
    max_refill = Decimal(str(settings.AI_AUTO_REFILL_MAX_AMOUNT))
    if refill_amount > max_refill:
        logger.error(
            "auto_refill_amount_exceeds_max",
            refill_amount=str(refill_amount),
            max_allowed=str(max_refill),
            payment_intent_id=payment_intent["id"],
        )
        return

    # Cross-check against the verified PaymentIntent amount
    verified_cents = payment_intent.get("amount") or 0
    verified_usd = Decimal(verified_cents) / 100
    if verified_usd > 0 and abs(refill_amount - verified_usd) > Decimal("0.01"):
        logger.error(
            "auto_refill_amount_mismatch",
            metadata_amount=str(refill_amount),
            verified_amount=str(verified_usd),
            payment_intent_id=payment_intent["id"],
        )
        refill_amount = verified_usd

    await wallet_service.topup(
        tenant_id,
        refill_amount,
        reference_id=f"auto_refill:{payment_intent['id']}",
        stripe_payment_intent_id=payment_intent["id"],
        description=f"Auto-refill: ${refill_amount}",
        db=db,
    )

    logger.info(
        "auto_refill_payment_succeeded",
        tenant_id=tenant_id_str,
        amount_usd=refill_amount_str,
        payment_intent_id=payment_intent["id"],
    )
