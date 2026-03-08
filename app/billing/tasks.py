"""Celery tasks for billing operations (auto-refill)."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import structlog
from sqlalchemy import select

from app.workers.celery_app import celery_app

logger = structlog.stdlib.get_logger()


@celery_app.task(
    bind=True,
    name="billing.process_auto_refill",
    soft_time_limit=30,
    time_limit=60,
    acks_late=True,
    max_retries=1,
    default_retry_delay=10,
)
def process_auto_refill(self, tenant_id: str) -> None:
    """Process an auto-refill for a tenant's wallet.

    Creates a Stripe PaymentIntent using the saved payment method,
    and credits the wallet on success.
    """
    asyncio.run(_async_process_auto_refill(tenant_id))


async def _async_process_auto_refill(tenant_id: str) -> None:
    """Async implementation of auto-refill."""
    from app.ai.wallet import wallet_service
    from app.config import settings
    from app.db.models.ai import DollarWallet
    from app.db.session import async_session_factory

    tid = uuid.UUID(tenant_id)

    async with async_session_factory() as db:
        result = await db.execute(
            select(DollarWallet).where(DollarWallet.tenant_id == tid)
        )
        wallet = result.scalar_one_or_none()
        if not wallet:
            logger.warning("auto_refill_no_wallet", tenant_id=tenant_id)
            return

        if not wallet.auto_refill_enabled:
            return
        if not wallet.stripe_payment_method_id:
            logger.warning("auto_refill_no_payment_method", tenant_id=tenant_id)
            return
        if wallet.auto_refill_amount_usd is None or wallet.auto_refill_threshold_usd is None:
            return

        # Re-check balance to avoid double-refill
        balance = await wallet_service.get_balance(tid)
        if balance > wallet.auto_refill_threshold_usd:
            logger.info("auto_refill_balance_above_threshold", tenant_id=tenant_id)
            return

        refill_amount = wallet.auto_refill_amount_usd

        # Look up Stripe customer ID from subscription
        from app.db.models.billing import Subscription

        sub_result = await db.execute(
            select(Subscription).where(Subscription.tenant_id == tid)
        )
        subscription = sub_result.scalar_one_or_none()
        if not subscription or not subscription.stripe_customer_id:
            logger.error("auto_refill_no_stripe_customer", tenant_id=tenant_id)
            return

        # Create PaymentIntent
        if not settings.stripe_configured:
            logger.error("auto_refill_stripe_not_configured", tenant_id=tenant_id)
            return

        try:
            import stripe

            stripe.api_key = settings.STRIPE_SECRET_KEY

            payment_intent = stripe.PaymentIntent.create(
                amount=int(refill_amount * 100),  # Convert to cents
                currency="usd",
                customer=subscription.stripe_customer_id,
                payment_method=wallet.stripe_payment_method_id,
                off_session=True,
                confirm=True,
                metadata={
                    "tenant_id": tenant_id,
                    "type": "auto_refill",
                    "refill_amount_usd": str(refill_amount),
                },
            )

            if payment_intent.status == "succeeded":
                # Credit wallet immediately
                await wallet_service.topup(
                    tid,
                    refill_amount,
                    reference_id=f"auto_refill:{payment_intent.id}",
                    stripe_payment_intent_id=payment_intent.id,
                    description=f"Auto-refill: ${refill_amount}",
                    db=db,
                )
                logger.info(
                    "auto_refill_succeeded",
                    tenant_id=tenant_id,
                    amount_usd=str(refill_amount),
                    payment_intent_id=payment_intent.id,
                )
            else:
                logger.warning(
                    "auto_refill_payment_not_succeeded",
                    tenant_id=tenant_id,
                    status=payment_intent.status,
                )

        except stripe.error.CardError as exc:
            logger.error(
                "auto_refill_card_error",
                tenant_id=tenant_id,
                error=str(exc),
            )
        except Exception as exc:
            logger.error(
                "auto_refill_failed",
                tenant_id=tenant_id,
                error=str(exc),
                exc_info=True,
            )
