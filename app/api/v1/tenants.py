"""Tenant management endpoints — admin-only.

All endpoints require the X-Admin-Key header.
"""

import secrets
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import hash_api_key
from app.api.deps import get_db, require_admin_key
from app.api.rate_limit import RateLimiter
from app.api.schemas import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
)
from app.config import settings
from app.core.audit import AuditAction, emit_audit_event
from app.core.cache import cached, invalidate
from app.core.pagination import CursorPage, paginate
from app.db.models import ApiKey, Tenant

_admin_rate_limit = RateLimiter(max_requests=60, window=60, key_prefix="rl:admin")
router = APIRouter(prefix="/tenants", dependencies=[Depends(require_admin_key), Depends(_admin_rate_limit)])
logger = structlog.stdlib.get_logger()

# Explicit allowlist of fields that can be updated via PATCH
_TENANT_MUTABLE_FIELDS = {"name", "plan", "is_active", "settings"}


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    tenant = Tenant(**body.model_dump(exclude_none=True))
    db.add(tenant)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Slug already taken") from None
    await db.refresh(tenant)
    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="tenant",
        resource_id=str(tenant.id),
        tenant_id=tenant.id,
        metadata={"slug": tenant.slug, "plan": tenant.plan},
    )
    await db.commit()
    logger.info("tenant_created", tenant_id=str(tenant.id), slug=tenant.slug)
    return tenant


@router.get("", response_model=CursorPage[TenantResponse])
async def list_tenants(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Tenant).where(Tenant.deleted_at.is_(None))
    return await paginate(db, stmt, Tenant.created_at, limit=limit, cursor=cursor, descending=True)


@cached(group="tenant", key="tenants:{tenant_id}")
async def _get_tenant_cached(tenant_id: uuid.UUID, db: AsyncSession) -> dict | None:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return None
    return TenantResponse.model_validate(tenant).model_dump(mode="json")


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    data = await _get_tenant_cached(tenant_id, db)
    if not data:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return data


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: uuid.UUID, body: TenantUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field not in _TENANT_MUTABLE_FIELDS:
            continue
        setattr(tenant, field, value)

    changes = body.model_dump(exclude_unset=True)
    await emit_audit_event(
        db,
        action=AuditAction.UPDATE,
        resource_type="tenant",
        resource_id=str(tenant.id),
        tenant_id=tenant.id,
        changes=changes,
    )
    await db.flush()
    await db.refresh(tenant)
    await db.commit()
    await invalidate(f"tenants:{tenant_id}")
    logger.info("tenant_updated", tenant_id=str(tenant.id))
    return tenant


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    now = datetime.now(UTC)
    tenant.deleted_at = now
    tenant.is_active = False

    # Cascade soft-delete: deactivate all child resources so they stop
    # working immediately.  Hard deletes happen via a background cleanup task.
    from app.db.models import (
        ApiKey,
        RefreshToken,
        Subscription,
        SubscriptionStatus,
        TenantFeatureOverride,
        User,
        WebhookEndpoint,
    )

    try:
        # Deactivate API keys
        await db.execute(
            update(ApiKey).where(ApiKey.tenant_id == tenant_id, ApiKey.active.is_(True)).values(active=False)
        )
        # Deactivate users and revoke their refresh tokens
        user_ids_result = await db.execute(select(User.id).where(User.tenant_id == tenant_id))
        user_ids = [row[0] for row in user_ids_result.all()]
        await db.execute(
            update(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)).values(is_active=False)
        )
        if user_ids:
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id.in_(user_ids), RefreshToken.revoked.is_(False))
                .values(revoked=True)
            )
        # Deactivate webhook endpoints
        await db.execute(
            update(WebhookEndpoint)
            .where(WebhookEndpoint.tenant_id == tenant_id, WebhookEndpoint.active.is_(True))
            .values(active=False)
        )
        # Cancel subscriptions
        await db.execute(
            update(Subscription)
            .where(
                Subscription.tenant_id == tenant_id,
                Subscription.status != SubscriptionStatus.CANCELED,
            )
            .values(status=SubscriptionStatus.CANCELED)
        )
        # Remove feature flag overrides
        from sqlalchemy import delete as sa_delete

        await db.execute(sa_delete(TenantFeatureOverride).where(TenantFeatureOverride.tenant_id == tenant_id))

        await emit_audit_event(
            db,
            action=AuditAction.DELETE,
            resource_type="tenant",
            resource_id=str(tenant.id),
            tenant_id=tenant.id,
            metadata={"slug": tenant.slug},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.error("tenant_delete_cascade_failed", tenant_id=str(tenant_id), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete tenant") from None

    await invalidate(f"tenants:{tenant_id}")
    logger.info("tenant_deleted", tenant_id=str(tenant.id), slug=tenant.slug)


@router.post("/{tenant_id}/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key_for_tenant(
    tenant_id: uuid.UUID,
    body: ApiKeyCreate | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key for a tenant. Returns the raw key once.

    Accepts an optional body with name, scopes, and rate_limit.
    Defaults to read-only scopes if none specified (least privilege).
    """
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Default to read-only scopes (least privilege) if none specified.
    # Exclude infrastructure scopes from defaults — they are UI-only.
    default_read_scopes = [
        s for s in settings.VALID_SCOPES if s.endswith(":read") and s not in settings.INFRASTRUCTURE_SCOPES
    ]
    key_name = body.name if body else "default"
    key_scopes = body.scopes if body and body.scopes else default_read_scopes
    key_rate_limit = body.rate_limit if body else 100

    # Reject infrastructure scopes that must never be granted to API keys
    forbidden = set(key_scopes) & settings.INFRASTRUCTURE_SCOPES
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot grant infrastructure scopes to API keys: {', '.join(sorted(forbidden))}",
        )

    raw_key = f"sk_{secrets.token_urlsafe(32)}"
    api_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=hash_api_key(raw_key),
        name=key_name,
        scopes=key_scopes,
        rate_limit=key_rate_limit,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)
    await db.commit()

    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="api_key",
        resource_id=str(api_key.id),
        tenant_id=tenant.id,
    )
    await db.commit()
    logger.info("api_key_created_for_tenant", tenant_id=str(tenant.id), key_id=str(api_key.id))
    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        rate_limit=api_key.rate_limit,
        scopes=api_key.scopes,
        active=api_key.active,
        created_at=api_key.created_at,
        raw_key=raw_key,
    )
