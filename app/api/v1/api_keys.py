"""API key management — scoped to the authenticated tenant."""

import secrets
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import hash_api_key
from app.api.deps import get_current_tenant, get_db
from app.api.schemas import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse, ApiKeyRevokeResponse
from app.db.models import ApiKey, Tenant

router = APIRouter(prefix="/api-keys")
logger = structlog.stdlib.get_logger()


@router.post("", response_model=ApiKeyCreatedResponse, status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    raw_key = f"sk_{secrets.token_urlsafe(32)}"
    api_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=hash_api_key(raw_key),
        name=body.name,
        rate_limit=body.rate_limit,
        scopes=body.scopes or [],
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info("api_key_created", tenant_id=str(tenant.id), key_id=str(api_key.id))
    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        rate_limit=api_key.rate_limit,
        scopes=api_key.scopes,
        active=api_key.active,
        created_at=api_key.created_at,
        raw_key=raw_key,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiKey).where(ApiKey.tenant_id == tenant.id).order_by(ApiKey.created_at.desc()))
    return list(result.scalars().all())


@router.delete("/{key_id}", response_model=ApiKeyRevokeResponse)
async def revoke_api_key(
    key_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant.id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.active = False
    await db.commit()
    logger.info("api_key_revoked", tenant_id=str(tenant.id), key_id=str(key_id))
    return ApiKeyRevokeResponse(id=key_id)
