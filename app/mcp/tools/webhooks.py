"""MCP tools for webhook management."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WebhookEndpoint
from app.mcp.errors import not_found_error, tool_error

logger = structlog.stdlib.get_logger()


async def webhook_list(*, tenant: Any, db: AsyncSession) -> list[dict]:
    """List all webhook endpoints for the tenant.

    Returns endpoint URLs, subscribed events, and active status.
    """
    result = await db.execute(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.tenant_id == tenant.id)
        .order_by(WebhookEndpoint.created_at.desc())
    )
    endpoints = result.scalars().all()

    return [
        {
            "id": str(ep.id),
            "url": ep.url,
            "events": ep.events,
            "active": ep.active,
            "description": ep.description,
            "created_at": ep.created_at.isoformat() if ep.created_at else None,
        }
        for ep in endpoints
    ]


async def webhook_create(
    url: str,
    events: list[str],
    description: str | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a webhook endpoint.

    The URL must be HTTPS. Events must be from the valid event list.
    A signing secret is generated automatically for verifying deliveries.
    """
    from app.api.v1.webhooks import VALID_WEBHOOK_EVENTS

    # Validate URL — full SSRF protection (DNS resolution, private IP checks)
    from app.core.url_validation import validate_webhook_url_async

    ssrf_error = await validate_webhook_url_async(url)
    if ssrf_error:
        raise tool_error(ssrf_error, hint="Provide a publicly reachable HTTPS URL")

    if not url.startswith("https://"):
        raise tool_error(
            "Webhook URL must use HTTPS.",
            hint="Provide a URL starting with https://",
        )

    # Validate events
    if not events:
        raise tool_error("At least one event is required.")
    invalid = [e for e in events if e not in VALID_WEBHOOK_EVENTS]
    if invalid:
        raise tool_error(
            f"Invalid events: {', '.join(invalid)}",
            hint=f"Valid events: {', '.join(VALID_WEBHOOK_EVENTS)}",
        )

    signing_secret = f"whsec_{secrets.token_urlsafe(32)}"

    endpoint = WebhookEndpoint(
        tenant_id=tenant.id,
        url=url,
        events=events,
        description=description,
        signing_secret=signing_secret,
        active=True,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)

    logger.info("mcp_webhook_created", endpoint_id=str(endpoint.id), tenant_id=str(tenant.id))

    return {
        "id": str(endpoint.id),
        "url": endpoint.url,
        "events": endpoint.events,
        "signing_secret": signing_secret,
        "warning": "Store this secret securely. It will not be shown again.",
        "active": True,
    }


async def webhook_delete(
    webhook_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Delete a webhook endpoint."""
    try:
        uid = uuid.UUID(webhook_id)
    except ValueError as exc:
        raise tool_error("Invalid webhook ID format") from exc

    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == uid,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    endpoint = result.scalar_one_or_none()

    if not endpoint:
        raise not_found_error("Webhook endpoint")

    await db.delete(endpoint)
    await db.commit()

    return {"id": str(uid), "deleted": True}
