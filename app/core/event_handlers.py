"""Central event handler registration — wires domain events to side effects.

Handlers for:
- Email notifications (via Brevo)
- In-app notification creation
- Webhook dispatch to subscribed endpoints

Import this module in app/main.py to register all handlers on startup.
"""

import structlog
from sqlalchemy import select

from app.core.email import EmailTemplate, send_email
from app.core.events import (
    DataExportRequested,
    InvitationSent,
    JobCompleted,
    JobFailed,
    SubscriptionChanged,
    UserRegistered,
    on,
)
from app.db.session import async_session_factory

logger = structlog.stdlib.get_logger()


async def _create_notification(
    user_id: str,
    tenant_id: str,
    notification_type: str,
    title: str,
    body: str | None = None,
    data: dict | None = None,
) -> None:
    """Create an in-app notification for a user."""
    import uuid

    from app.db.models import Notification

    try:
        async with async_session_factory() as db:
            notification = Notification(
                user_id=uuid.UUID(user_id),
                tenant_id=uuid.UUID(tenant_id),
                type=notification_type,
                title=title,
                body=body,
                data=data or {},
            )
            db.add(notification)
            await db.commit()
    except Exception:
        logger.error("notification_create_failed", user_id=user_id, type=notification_type, exc_info=True)


async def _dispatch_webhooks(tenant_id: str, event_name: str, payload: dict) -> None:
    """Dispatch event to all subscribed webhook endpoints for a tenant."""
    import uuid

    from app.db.models import WebhookEndpoint

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(WebhookEndpoint).where(
                    WebhookEndpoint.tenant_id == uuid.UUID(tenant_id),
                    WebhookEndpoint.active.is_(True),
                )
            )
            endpoints = result.scalars().all()

            for endpoint in endpoints:
                if event_name in (endpoint.events or []):
                    try:
                        from app.workers.tasks import deliver_webhook

                        deliver_webhook.delay(
                            endpoint.url,
                            {"event": event_name, **payload},
                            signing_secret=endpoint.get_secret(),
                        )
                    except Exception:
                        logger.error(
                            "webhook_dispatch_failed",
                            endpoint_id=str(endpoint.id),
                            event=event_name,
                            exc_info=True,
                        )
    except Exception:
        logger.error("webhook_dispatch_error", tenant_id=tenant_id, event=event_name, exc_info=True)


async def _get_tenant_owner_id(tenant_id: str) -> str | None:
    """Get the owner user ID for a tenant."""
    import uuid

    from app.db.models import TenantMembership, UserRole

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(TenantMembership.user_id).where(
                    TenantMembership.tenant_id == uuid.UUID(tenant_id),
                    TenantMembership.role == UserRole.OWNER,
                )
            )
            row = result.scalars().first()
            return str(row) if row else None
    except Exception:
        logger.error("tenant_owner_lookup_failed", tenant_id=tenant_id, exc_info=True)
        return None


# ── Event handlers ──────────────────────────────────────


@on(UserRegistered)
async def handle_user_registered(event: UserRegistered) -> None:
    """Send welcome email on registration."""
    from app.config import settings

    verify_url = f"{settings.APP_BASE_URL}/verify-email"
    docs_url = f"{settings.APP_BASE_URL}/docs"
    await send_email(
        to=event.email,
        template=EmailTemplate.WELCOME,
        context={
            "display_name": event.email.split("@")[0],
            "verify_url": verify_url,
            "docs_url": docs_url,
        },
    )


@on(InvitationSent)
async def handle_invitation_sent(event: InvitationSent) -> None:
    """Send invitation email."""
    from app.db.models import Tenant, User

    async with async_session_factory() as db:
        # Load tenant and inviter names
        import uuid

        tenant_result = await db.execute(
            select(Tenant).where(Tenant.id == uuid.UUID(event.tenant_id))
        )
        tenant = tenant_result.scalar_one_or_none()
        tenant_name = tenant.name if tenant else "the team"

        inviter_result = await db.execute(
            select(User).where(User.id == uuid.UUID(event.invited_by))
        )
        inviter = inviter_result.scalar_one_or_none()
        inviter_name = inviter.display_name or inviter.email if inviter else "A team member"

    await send_email(
        to=event.email,
        template=EmailTemplate.INVITATION,
        context={
            "inviter_name": inviter_name,
            "tenant_name": tenant_name,
            "role": event.role,
            "invite_url": event.accept_url,
        },
    )


@on(JobCompleted)
async def handle_job_completed(event: JobCompleted) -> None:
    """Create in-app notification and dispatch webhook for job completion."""
    # Notify tenant owner
    owner_id = await _get_tenant_owner_id(event.tenant_id)
    if owner_id:
        await _create_notification(
            user_id=owner_id,
            tenant_id=event.tenant_id,
            notification_type="job.completed",
            title=f"Job completed: {event.job_type}",
            body=f"Job {event.job_id} has completed successfully.",
            data={"job_id": event.job_id, "job_type": event.job_type},
        )

    await _dispatch_webhooks(event.tenant_id, "job.completed", {
        "job_id": event.job_id,
        "job_type": event.job_type,
    })


@on(JobFailed)
async def handle_job_failed(event: JobFailed) -> None:
    """Create in-app notification and dispatch webhook for job failure."""
    owner_id = await _get_tenant_owner_id(event.tenant_id)
    if owner_id:
        await _create_notification(
            user_id=owner_id,
            tenant_id=event.tenant_id,
            notification_type="job.failed",
            title=f"Job failed: {event.job_type}",
            body=f"Job {event.job_id} failed: {event.error}",
            data={"job_id": event.job_id, "job_type": event.job_type, "error": event.error},
        )

    await _dispatch_webhooks(event.tenant_id, "job.failed", {
        "job_id": event.job_id,
        "job_type": event.job_type,
        "error": event.error,
    })


@on(SubscriptionChanged)
async def handle_subscription_changed(event: SubscriptionChanged) -> None:
    """Dispatch webhook for subscription changes."""
    await _dispatch_webhooks(event.tenant_id, "subscription.changed", {
        "old_plan": event.old_plan,
        "new_plan": event.new_plan,
    })


@on(DataExportRequested)
async def handle_export_requested(event: DataExportRequested) -> None:
    """Log export request for auditing."""
    logger.info(
        "export_event_received",
        tenant_id=event.tenant_id,
        user_id=event.user_id,
        export_type=event.export_type,
    )
