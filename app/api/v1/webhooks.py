"""Webhook management endpoints — self-service webhook configuration.

Tenants can register webhook endpoints, subscribe to events, and view delivery logs.
"""

import secrets
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.core.audit import AuditAction, emit_audit_event
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.core.url_validation import validate_webhook_url_async
from app.db.models import Tenant, WebhookDelivery, WebhookEndpoint

router = APIRouter(prefix="/webhooks")
logger = structlog.stdlib.get_logger()

VALID_WEBHOOK_EVENTS = [
    "job.created",
    "job.completed",
    "job.failed",
    "file.uploaded",
    "file.deleted",
    "member.added",
    "member.removed",
    "invitation.sent",
    "subscription.changed",
    "export.completed",
]


# ── Schemas ──────────────────────────────────────────────


class WebhookEndpointCreate(BaseModel):
    url: HttpUrl
    description: str | None = Field(default=None, max_length=255)
    events: list[str] = Field(..., min_length=1, max_length=20)

    def model_post_init(self, __context):
        invalid = [e for e in self.events if e not in VALID_WEBHOOK_EVENTS]
        if invalid:
            raise ValueError(f"Invalid events: {', '.join(invalid)}")


class WebhookEndpointUpdate(BaseModel):
    url: HttpUrl | None = None
    description: str | None = Field(default=None, max_length=255)
    events: list[str] | None = Field(default=None, min_length=1, max_length=20)
    active: bool | None = None


class WebhookEndpointResponse(BaseModel):
    id: uuid.UUID
    url: str
    description: str | None
    events: list[str]
    active: bool
    created_at: object
    updated_at: object

    model_config = {"from_attributes": True}


class WebhookEndpointCreatedResponse(WebhookEndpointResponse):
    secret: str


class WebhookDeliveryResponse(BaseModel):
    id: uuid.UUID
    event: str
    status_code: int | None
    attempts: int
    created_at: object
    completed_at: object | None

    model_config = {"from_attributes": True}


# ── Endpoints ────────────────────────────────────────────


@router.post(
    "",
    response_model=WebhookEndpointCreatedResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("webhooks:write"))],
)
async def create_webhook_endpoint(
    body: WebhookEndpointCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Register a new webhook endpoint."""
    url = str(body.url)
    ssrf_error = await validate_webhook_url_async(url)
    if ssrf_error:
        raise HTTPException(status_code=422, detail=f"Invalid webhook URL: {ssrf_error}")

    raw_secret = f"whsec_{secrets.token_urlsafe(32)}"

    endpoint = WebhookEndpoint(
        tenant_id=tenant.id,
        url=url,
        description=body.description,
        secret="",  # Will be set via set_secret() below
        events=body.events,
    )
    endpoint.set_secret(raw_secret)  # Encrypt at rest — never store plaintext
    db.add(endpoint)

    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="webhook_endpoint",
        resource_id=str(endpoint.id),
        tenant_id=tenant.id,
        metadata={"url": url, "events": body.events},
    )
    await db.flush()
    await db.refresh(endpoint)
    await db.commit()

    logger.info("webhook_endpoint_created", tenant_id=str(tenant.id), endpoint_id=str(endpoint.id))
    return WebhookEndpointCreatedResponse(
        id=endpoint.id,
        url=endpoint.url,
        description=endpoint.description,
        events=endpoint.events,
        active=endpoint.active,
        secret=raw_secret,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


@router.get(
    "",
    response_model=list[WebhookEndpointResponse],
    dependencies=[Depends(RequireScopes("webhooks:read"))],
)
async def list_webhook_endpoints(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all webhook endpoints for the tenant."""
    stmt = tenant_query(select(WebhookEndpoint), tenant).where(WebhookEndpoint.active.is_(True)).order_by(WebhookEndpoint.created_at.desc())
    result = await db.execute(stmt)
    endpoints = result.scalars().all()
    return endpoints


@router.get(
    "/{endpoint_id}",
    response_model=WebhookEndpointResponse,
    dependencies=[Depends(RequireScopes("webhooks:read"))],
)
async def get_webhook_endpoint(
    endpoint_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    return endpoint


@router.patch(
    "/{endpoint_id}",
    response_model=WebhookEndpointResponse,
    dependencies=[Depends(RequireScopes("webhooks:write"))],
)
async def update_webhook_endpoint(
    endpoint_id: uuid.UUID,
    body: WebhookEndpointUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    changes = {}
    if body.url is not None:
        url = str(body.url)
        ssrf_error = await validate_webhook_url_async(url)
        if ssrf_error:
            raise HTTPException(status_code=422, detail=f"Invalid webhook URL: {ssrf_error}")
        changes["url"] = [endpoint.url, url]
        endpoint.url = url
    if body.description is not None:
        endpoint.description = body.description
    if body.events is not None:
        invalid = [e for e in body.events if e not in VALID_WEBHOOK_EVENTS]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid events: {', '.join(invalid)}")
        changes["events"] = [endpoint.events, body.events]
        endpoint.events = body.events
    if body.active is not None:
        changes["active"] = [endpoint.active, body.active]
        endpoint.active = body.active

    await emit_audit_event(
        db,
        action=AuditAction.UPDATE,
        resource_type="webhook_endpoint",
        resource_id=str(endpoint_id),
        tenant_id=tenant.id,
        changes=changes,
    )
    await db.flush()
    await db.refresh(endpoint)
    await db.commit()
    return endpoint


@router.delete(
    "/{endpoint_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("webhooks:write"))],
)
async def delete_webhook_endpoint(
    endpoint_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    endpoint.active = False
    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="webhook_endpoint",
        resource_id=str(endpoint_id),
        tenant_id=tenant.id,
    )
    await db.commit()
    logger.info("webhook_endpoint_deleted", endpoint_id=str(endpoint_id))


@router.get(
    "/{endpoint_id}/deliveries",
    response_model=CursorPage[WebhookDeliveryResponse],
    dependencies=[Depends(RequireScopes("webhooks:read"))],
)
async def list_webhook_deliveries(
    endpoint_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List delivery history for a webhook endpoint."""
    # Verify endpoint belongs to tenant
    ep_result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    if not ep_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    # Join through WebhookEndpoint to enforce tenant isolation — prevents
    # cross-tenant data access if endpoint_id is guessed/leaked.
    stmt = (
        select(WebhookDelivery)
        .join(WebhookEndpoint, WebhookDelivery.endpoint_id == WebhookEndpoint.id)
        .where(
            WebhookDelivery.endpoint_id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    return await paginate(db, stmt, WebhookDelivery.created_at, limit=limit, cursor=cursor, descending=True)


@router.post(
    "/{endpoint_id}/test",
    dependencies=[Depends(RequireScopes("webhooks:write"))],
)
async def test_webhook_endpoint(
    endpoint_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Send a test event to a webhook endpoint."""
    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    endpoint = result.scalar_one_or_none()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    if not endpoint.active:
        raise HTTPException(status_code=400, detail="Webhook endpoint is inactive")

    # Dispatch test webhook via Celery
    try:
        from app.workers.tasks import deliver_webhook

        test_payload = {
            "event": "webhook.test",
            "endpoint_id": str(endpoint_id),
            "message": "This is a test webhook delivery.",
        }
        deliver_webhook.delay(endpoint.url, test_payload, signing_secret=endpoint.get_secret())
    except Exception:
        logger.error("webhook_test_dispatch_failed", endpoint_id=str(endpoint_id), exc_info=True)
        raise HTTPException(status_code=503, detail="Failed to dispatch test webhook") from None

    return {"status": "dispatched", "endpoint_id": str(endpoint_id)}
