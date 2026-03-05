from collections.abc import AsyncGenerator

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import hash_api_key
from app.db.models import ApiKey, Tenant
from app.db.session import get_session


async def get_db() -> AsyncGenerator[AsyncSession]:
    async for session in get_session():
        yield session


async def get_current_tenant(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    key_hash = hash_api_key(x_api_key)

    result = await db.execute(
        select(ApiKey).options(selectinload(ApiKey.tenant)).where(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
    )
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    tenant = api_key.tenant
    if tenant is None or not tenant.is_active:
        raise HTTPException(status_code=403, detail="Tenant not found or inactive")

    return tenant
