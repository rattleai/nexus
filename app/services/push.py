"""Push notification delivery service.

Supports Web Push (VAPID) and Firebase Cloud Messaging (FCM).
Designed to be called from Celery tasks for async delivery.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = structlog.stdlib.get_logger()


async def send_push_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    url: str | None = None,
) -> int:
    """Send push notification to all active subscriptions for a user.

    Returns the number of successfully sent notifications.
    """
    from app.db.models.mobile import PushSubscription

    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.active.is_(True),
        )
    )
    subscriptions = result.scalars().all()

    if not subscriptions:
        return 0

    sent = 0
    expired_ids: list[uuid.UUID] = []

    for sub in subscriptions:
        try:
            if sub.platform == "web":
                success = await _send_web_push(sub.subscription_data, title, body, data, url)
            elif sub.platform == "fcm":
                success = await _send_fcm(sub.subscription_data, title, body, data)
            else:
                logger.warning("push_unsupported_platform", platform=sub.platform)
                continue

            if success:
                sent += 1
            else:
                expired_ids.append(sub.id)
        except Exception:
            logger.warning("push_send_error", subscription_id=str(sub.id), exc_info=True)
            expired_ids.append(sub.id)

    # Mark expired subscriptions as inactive
    if expired_ids:
        await db.execute(
            update(PushSubscription)
            .where(PushSubscription.id.in_(expired_ids))
            .values(active=False)
        )
        await db.commit()

    logger.info("push_sent", user_id=str(user_id), sent=sent, expired=len(expired_ids))
    return sent


async def _send_web_push(
    subscription_data: dict[str, Any],
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
    url: str | None = None,
) -> bool:
    """Send a Web Push notification using VAPID.

    Requires VAPID_PRIVATE_KEY and VAPID_MAILTO in settings.
    Returns True on success, False if subscription expired (410).
    """
    vapid_private_key = getattr(settings, "VAPID_PRIVATE_KEY", "")
    vapid_mailto = getattr(settings, "VAPID_MAILTO", "")

    if not vapid_private_key:
        logger.warning("web_push_no_vapid_key")
        return False

    try:
        from pywebpush import webpush, WebPushException

        payload = json.dumps({
            "title": title,
            "body": body,
            "data": data or {},
            "url": url,
        })

        webpush(
            subscription_info=subscription_data,
            data=payload,
            vapid_private_key=vapid_private_key,
            vapid_claims={"sub": f"mailto:{vapid_mailto}"},
        )
        return True
    except Exception as e:
        error_str = str(e)
        if "410" in error_str or "404" in error_str:
            return False  # Subscription expired
        logger.warning("web_push_error", error=error_str)
        raise


async def _send_fcm(
    subscription_data: dict[str, Any],
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> bool:
    """Send an FCM notification via Firebase Admin SDK.

    Requires FIREBASE_SERVICE_ACCOUNT_JSON in settings.
    Returns True on success, False if token is invalid.
    """
    device_token = subscription_data.get("token", "")
    if not device_token:
        return False

    try:
        import firebase_admin
        from firebase_admin import messaging

        # Initialize Firebase app if not already done
        if not firebase_admin._apps:
            firebase_service_account = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "")
            if not firebase_service_account:
                logger.warning("fcm_no_service_account")
                return False

            import json as json_mod
            cred = firebase_admin.credentials.Certificate(json_mod.loads(firebase_service_account))
            firebase_admin.initialize_app(cred)

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=device_token,
        )
        messaging.send(message)
        return True
    except Exception as e:
        if "not-registered" in str(e).lower() or "invalid-registration" in str(e).lower():
            return False
        logger.warning("fcm_error", error=str(e))
        raise
