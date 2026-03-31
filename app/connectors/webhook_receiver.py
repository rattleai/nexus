"""Inbound webhook receiver for connector events.

Receives webhooks from external services, verifies signatures,
and routes events to matching workflow triggers or event handlers.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.connectors.models import ConnectorAuditLog, ConnectorDefinition

logger = structlog.stdlib.get_logger()

router = APIRouter()


@router.post("/connectors/{slug}/webhook")
async def receive_webhook(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive and process an inbound webhook from a connector.

    Verifies the webhook signature if configured, then dispatches
    the event to registered handlers.
    """
    # Look up connector definition
    result = await db.execute(
        select(ConnectorDefinition).where(
            ConnectorDefinition.slug == slug,
            ConnectorDefinition.is_active.is_(True),
        )
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    webhook_config = connector.webhook_config or {}

    # Read the raw body for signature verification
    body = await request.body()

    # Verify signature if configured
    signature_header = webhook_config.get("signature_header")
    signature_algo = webhook_config.get("signature_algo", "sha256")
    webhook_secret = webhook_config.get("secret")

    if signature_header and webhook_secret:
        received_sig = request.headers.get(signature_header, "")
        if not _verify_signature(body, received_sig, webhook_secret, signature_algo):
            logger.warning(
                "webhook_signature_invalid",
                connector=slug,
                header=signature_header,
            )
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse the event
    try:
        import json
        payload = json.loads(body)
    except Exception:
        payload = {"raw": body.decode("utf-8", errors="replace")[:10000]}

    event_type = _extract_event_type(request, payload, webhook_config)

    logger.info(
        "webhook_received",
        connector=slug,
        event_type=event_type,
        content_length=len(body),
    )

    # Dispatch the event
    dispatched = await _dispatch_webhook_event(
        connector_slug=slug,
        event_type=event_type,
        payload=payload,
        db=db,
    )

    # Audit log
    audit = ConnectorAuditLog(
        tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # System-level
        action="webhook_receive",
        tool_name=event_type,
        status="success",
        actor_type="system",
        request_summary={"event_type": event_type, "dispatched": dispatched},
    )
    db.add(audit)
    await db.commit()

    return {"status": "ok", "event_type": event_type, "dispatched": dispatched}


def _verify_signature(
    body: bytes,
    received_signature: str,
    secret: str,
    algorithm: str = "sha256",
) -> bool:
    """Verify a webhook signature using HMAC."""
    if algorithm == "sha256":
        expected = hmac.new(
            secret.encode(), body, hashlib.sha256,
        ).hexdigest()
    elif algorithm == "sha1":
        expected = hmac.new(
            secret.encode(), body, hashlib.sha1,
        ).hexdigest()
    else:
        logger.warning("webhook_unsupported_algo", algorithm=algorithm)
        return False

    # Handle "sha256=..." prefix format (GitHub style)
    if "=" in received_signature:
        received_signature = received_signature.split("=", 1)[1]

    return hmac.compare_digest(expected, received_signature)


def _extract_event_type(
    request: Request,
    payload: dict[str, Any],
    webhook_config: dict[str, Any],
) -> str:
    """Extract the event type from the webhook request.

    Tries:
    1. A configured event_type_header (e.g. X-GitHub-Event)
    2. Common payload fields (event, type, action, event_type)
    3. Falls back to "unknown"
    """
    # From header
    event_header = webhook_config.get("event_type_header")
    if event_header:
        value = request.headers.get(event_header)
        if value:
            return value

    # From payload
    for key in ("event", "type", "action", "event_type", "event_name"):
        if key in payload and isinstance(payload[key], str):
            return payload[key]

    return "unknown"


async def _dispatch_webhook_event(
    connector_slug: str,
    event_type: str,
    payload: dict[str, Any],
    db: AsyncSession,
) -> int:
    """Dispatch a webhook event to registered handlers.

    Currently emits a domain event that workflow triggers can match.
    Returns the number of handlers dispatched to.
    """
    try:
        from app.connectors.events import ConnectionStatusChanged
        from app.core.events import emit

        # Emit a generic webhook event that can be consumed by
        # workflow triggers or custom event handlers
        from dataclasses import dataclass, field
        from app.core.events import DomainEvent

        @dataclass
        class ConnectorWebhookReceived(DomainEvent):
            connector_slug: str = ""
            event_type: str = ""
            payload: dict = field(default_factory=dict)

        await emit(ConnectorWebhookReceived(
            connector_slug=connector_slug,
            event_type=event_type,
            payload=payload,
        ))
        return 1
    except Exception:
        logger.debug("webhook_dispatch_failed", exc_info=True)
        return 0
