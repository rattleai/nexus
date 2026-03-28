"""API key management — UI-only, scoped to the authenticated tenant.

These endpoints are restricted to JWT-authenticated (UI) sessions to prevent
privilege-escalation attacks where a programmatic API key creates new keys
with broader scopes.
"""

import secrets
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import hash_api_key
from app.api.deps import RequireUI, get_current_tenant, get_db
from app.api.schemas import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse, ApiKeyRevokeResponse
from app.config import settings
from app.core.pagination import CursorPage, paginate
from app.db.models import ApiKey, Tenant

router = APIRouter(prefix="/api-keys", dependencies=[Depends(RequireUI())])
logger = structlog.stdlib.get_logger()


def _validate_scopes(scopes: list[str]) -> list[str]:
    """Reject infrastructure scopes that must never be granted to API keys."""
    forbidden = set(scopes) & settings.INFRASTRUCTURE_SCOPES
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot grant infrastructure scopes to API keys: {', '.join(sorted(forbidden))}",
        )
    return scopes


@router.post(
    "",
    response_model=ApiKeyCreatedResponse,
    status_code=201,
)
async def create_api_key(
    body: ApiKeyCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Deduplicate scopes
    scopes = list(dict.fromkeys(body.scopes)) if body.scopes else []
    _validate_scopes(scopes)

    raw_key = f"sk_{secrets.token_urlsafe(32)}"
    api_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=hash_api_key(raw_key),
        name=body.name,
        rate_limit=body.rate_limit,
        scopes=scopes,
    )
    db.add(api_key)
    await db.flush()
    await db.refresh(api_key)
    await db.commit()

    logger.info(
        "audit.api_key_created", tenant_id=str(tenant.id), key_id=str(api_key.id), name=body.name, scopes=scopes,
    )
    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        rate_limit=api_key.rate_limit,
        scopes=api_key.scopes,
        active=api_key.active,
        created_at=api_key.created_at,
        raw_key=raw_key,
    )


@router.get(
    "",
    response_model=CursorPage[ApiKeyResponse],
)
async def list_api_keys(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    active: bool | None = Query(default=None, description="Filter by active/revoked status"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ApiKey).where(ApiKey.tenant_id == tenant.id)
    if active is not None:
        stmt = stmt.where(ApiKey.active == active)
    return await paginate(db, stmt, ApiKey.created_at, limit=limit, cursor=cursor, descending=True)


@router.delete(
    "/{key_id}",
    response_model=ApiKeyRevokeResponse,
)
async def revoke_api_key(
    key_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant.id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    if not api_key.active:
        return ApiKeyRevokeResponse(id=key_id)

    api_key.active = False
    await db.commit()
    logger.info("audit.api_key_revoked", tenant_id=str(tenant.id), key_id=str(key_id))
    return ApiKeyRevokeResponse(id=key_id)
