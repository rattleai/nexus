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


async def get_current_api_key(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Resolve and validate the API key from the request header."""
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

    return api_key


async def get_current_tenant(
    api_key: ApiKey = Depends(get_current_api_key),
) -> Tenant:
    """Return the tenant associated with the current API key."""
    return api_key.tenant


class RequireScopes:
    """FastAPI dependency that enforces API key scopes.

    Usage:
        @router.post("/jobs", dependencies=[Depends(RequireScopes("jobs:write"))])
        async def create_job(...): ...

    If the API key has an empty scopes list, all scopes are granted (superkey).
    """

    def __init__(self, *required: str):
        self.required = set(required)

    async def __call__(self, api_key: ApiKey = Depends(get_current_api_key)) -> None:
        # Empty/null scopes = unrestricted access (superkey)
        if not api_key.scopes:
            return

        granted = set(api_key.scopes)
        missing = self.required - granted
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"API key missing required scopes: {', '.join(sorted(missing))}",
            )
