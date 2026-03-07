"""Push notification subscription management.

Supports Web Push (VAPID), FCM (Firebase), and APNs platforms.
Mobile and web clients register their push subscriptions here.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_token, get_db
from app.db.models import User

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/push", tags=["push"])


@router.get("/vapid-key")
async def get_vapid_public_key() -> dict[str, str]:
    """Return the VAPID public key for Web Push subscription registration.

    No authentication required — clients need this before they can subscribe.
    """
    from app.config import settings

    if not settings.VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="Web Push not configured")
    return {"publicKey": settings.VAPID_PUBLIC_KEY}


class PushSubscriptionCreate(BaseModel):
    platform: str = Field(..., description="Push platform: web, fcm, apns")
    subscription_data: dict[str, Any] = Field(
        ..., description="Platform-specific subscription data (Web Push subscription object or device token)"
    )
    device_name: str | None = Field(None, max_length=255)


class PushSubscriptionResponse(BaseModel):
    id: str
    platform: str
    device_name: str | None
    active: bool
    created_at: str

    model_config = {"from_attributes": True}


@router.post("/subscribe", response_model=PushSubscriptionResponse, status_code=201)
async def subscribe_push(
    body: PushSubscriptionCreate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Register a push notification subscription for the current user."""
    from app.db.models.mobile import PushSubscription

    if body.platform not in ("web", "fcm", "apns"):
        raise HTTPException(status_code=400, detail="Platform must be web, fcm, or apns")

    # Check for existing subscription with same platform + subscription_data
    existing = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == user.id,
            PushSubscription.platform == body.platform,
            PushSubscription.subscription_data == body.subscription_data,
        )
    )
    subscription = existing.scalar_one_or_none()

    if subscription:
        # Re-activate existing subscription and update device name
        subscription.active = True
        subscription.device_name = body.device_name
    else:
        subscription = PushSubscription(
            user_id=user.id,
            tenant_id=user.tenant_id,
            platform=body.platform,
            subscription_data=body.subscription_data,
            device_name=body.device_name,
            active=True,
        )
        db.add(subscription)

    await db.commit()
    await db.refresh(subscription)

    logger.info("push_subscribed", user_id=str(user.id), platform=body.platform)

    return {
        "id": str(subscription.id),
        "platform": subscription.platform,
        "device_name": subscription.device_name,
        "active": subscription.active,
        "created_at": subscription.created_at.isoformat(),
    }


@router.delete("/subscribe/{subscription_id}", status_code=204)
async def unsubscribe_push(
    subscription_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Unregister a push notification subscription."""
    from app.db.models.mobile import PushSubscription

    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.id == subscription_id,
            PushSubscription.user_id == user.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    await db.delete(subscription)
    await db.commit()
    logger.info("push_unsubscribed", subscription_id=str(subscription_id))


@router.get("/subscriptions", response_model=list[PushSubscriptionResponse])
async def list_subscriptions(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all push subscriptions for the current user."""
    from app.db.models.mobile import PushSubscription

    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == user.id,
            PushSubscription.active.is_(True),
        )
    )
    subscriptions = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "platform": s.platform,
            "device_name": s.device_name,
            "active": s.active,
            "created_at": s.created_at.isoformat(),
        }
        for s in subscriptions
    ]
