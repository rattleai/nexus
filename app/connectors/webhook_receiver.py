"""Inbound webhook receiver for connector events.

Security hardening over PR #63:

* **P0.1** — Webhook secrets are looked up per-tenant via
  ``ConnectorAppCredential`` instead of being read from the global
  ``connector_definitions.webhook_config`` JSONB.
* **P0.9** — The webhook endpoint now carries a tenant ID in the URL path
  (``/connectors/{slug}/webhook/{tenant_id}``) so signature verification
  can use the correct per-tenant secret and audit rows reference the real
  tenant instead of a placeholder UUID.
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
from app.connectors.app_credentials import app_credential_manager
from app.connectors.models import ConnectorAuditLog, ConnectorDefinition
from app.db.session import set_tenant_context

logger = structlog.stdlib.get_logger()

router = APIRouter()


@router.post("/connectors/{slug}/webhook/{tenant_id}")
async def receive_webhook(
    slug: str,
    tenant_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive and process an inbound webhook from a connector.

    The URL path encodes the tenant so the correct per-tenant webhook secret
    can be looked up and audit entries reference the actual tenant.
    Providers include this URL as the webhook target when the tenant admin
    registers the OAuth app.
    """
    await set_tenant_context(db, str(tenant_id))

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

    # Secret comes from per-tenant app credentials — never from the global
    # connector definition (P0.1)
    webhook_secret: str | None = None
    try:
        app_creds = await app_credential_manager.get(
            tenant_id=tenant_id,
            connector_slug=slug,
            db=db,
        )
        if app_creds:
            webhook_secret = app_creds.webhook_secret
    except Exception:
        logger.debug("webhook_app_creds_lookup_failed", exc_info=True)

    if signature_header and webhook_secret:
        received_sig = request.headers.get(signature_header, "")
        if not _verify_signature(body, received_sig, webhook_secret, signature_algo):
            logger.warning(
                "webhook_signature_invalid",
                connector=slug,
                tenant_id=str(tenant_id),
                header=signature_header,
            )
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    elif signature_header and not webhook_secret:
        # Signature required by config but no secret registered → reject.
        logger.warning(
            "webhook_secret_missing",
            connector=slug,
            tenant_id=str(tenant_id),
        )
        raise HTTPException(
            status_code=401,
            detail="Webhook signature required but no secret is registered for this tenant",
        )

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
        tenant_id=str(tenant_id),
        event_type=event_type,
        content_length=len(body),
    )

    dispatched = await _dispatch_webhook_event(
        connector_slug=slug,
        tenant_id=tenant_id,
        event_type=event_type,
        payload=payload,
        db=db,
    )

    # Audit log with the real tenant, not a placeholder UUID
    audit = ConnectorAuditLog(
        tenant_id=tenant_id,
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
            secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
    elif algorithm == "sha1":
        expected = hmac.new(
            secret.encode(),
            body,
            hashlib.sha1,
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
    """Extract the event type from the webhook request."""
    event_header = webhook_config.get("event_type_header")
    if event_header:
        value = request.headers.get(event_header)
        if value:
            return value

    for key in ("event", "type", "action", "event_type", "event_name"):
        if key in payload and isinstance(payload[key], str):
            return payload[key]

    return "unknown"


async def _dispatch_webhook_event(
    connector_slug: str,
    tenant_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    db: AsyncSession,
) -> int:
    """Dispatch a webhook event via the domain event bus."""
    try:
        from dataclasses import dataclass, field

        from app.core.events import DomainEvent, emit

        @dataclass
        class ConnectorWebhookReceived(DomainEvent):
            tenant_id: str = ""
            connector_slug: str = ""
            event_type: str = ""
            payload: dict = field(default_factory=dict)

        await emit(
            ConnectorWebhookReceived(
                tenant_id=str(tenant_id),
                connector_slug=connector_slug,
                event_type=event_type,
                payload=payload,
            )
        )
        return 1
    except Exception:
        logger.debug("webhook_dispatch_failed", exc_info=True)
        return 0
