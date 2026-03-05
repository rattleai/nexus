"""Tenant management endpoints — admin-only.

All endpoints require the X-Admin-Key header matching the application SECRET_KEY.
"""

import secrets
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import hash_api_key
from app.api.deps import get_db, require_admin_key
from app.api.schemas import (
    ApiKeyCreatedResponse,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
)
from app.core.cache import cached, invalidate
from app.core.pagination import CursorPage, paginate
from app.db.models import ApiKey, Tenant

router = APIRouter(prefix="/tenants", dependencies=[Depends(require_admin_key)])
logger = structlog.stdlib.get_logger()


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Slug already taken")

    tenant = Tenant(**body.model_dump(exclude_none=True))
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    logger.info("audit.tenant_created", tenant_id=str(tenant.id), slug=tenant.slug)
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
        setattr(tenant, field, value)

    await db.commit()
    await db.refresh(tenant)
    await invalidate(f"tenants:{tenant_id}")
    logger.info("audit.tenant_updated", tenant_id=str(tenant.id))
    return tenant


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.deleted_at = datetime.now(UTC)
    await db.commit()
    await invalidate(f"tenants:{tenant_id}")
    logger.info("audit.tenant_deleted", tenant_id=str(tenant.id), slug=tenant.slug)


@router.post("/{tenant_id}/api-keys", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key_for_tenant(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key for a tenant. Returns the raw key once."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    raw_key = f"sk_{secrets.token_urlsafe(32)}"
    api_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=hash_api_key(raw_key),
        name="default",
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info("audit.api_key_created_for_tenant", tenant_id=str(tenant.id), key_id=str(api_key.id))
    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        rate_limit=api_key.rate_limit,
        scopes=api_key.scopes,
        active=api_key.active,
        created_at=api_key.created_at,
        raw_key=raw_key,
    )
