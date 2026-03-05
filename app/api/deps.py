import hmac
import uuid
from collections.abc import AsyncGenerator

import jwt
import structlog
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import hash_api_key
from app.config import settings
from app.db.models import ApiKey, Tenant, TenantMembership, User
from app.db.session import get_read_session, get_session, set_tenant_context

logger = structlog.stdlib.get_logger()


async def get_db() -> AsyncGenerator[AsyncSession]:
    async for session in get_session():
        yield session


async def get_read_db() -> AsyncGenerator[AsyncSession]:
    """Get a read-only DB session (uses read replica if configured)."""
    async for session in get_read_session():
        yield session


# ── API Key auth (existing) ─────────────────────────────


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
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Return the tenant associated with the current API key.

    Also sets PostgreSQL RLS tenant context for defense-in-depth isolation.
    """
    tenant = api_key.tenant
    await set_tenant_context(db, str(tenant.id))
    return tenant


# ── JWT auth (new, opt-in via AUTH_ENABLED) ──────────────


async def get_current_user_from_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT Bearer token, return the authenticated user.

    Raises 401 if the token is missing, expired, or invalid.
    """
    from app.core.security import decode_access_token

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[7:]
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token") from None

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid token payload") from None

    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Set RLS tenant context for defense-in-depth isolation (mirrors API key auth path)
    await set_tenant_context(db, str(user.tenant_id))

    return user


class RequireRole:
    """FastAPI dependency that enforces user roles via tenant membership.

    Usage:
        @router.get("/admin", dependencies=[Depends(RequireRole("admin", "owner"))])
        async def admin_only(...): ...
    """

    def __init__(self, *required_roles: str):
        self.required_roles = set(required_roles)

    async def __call__(
        self,
        user: User = Depends(get_current_user_from_token),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        result = await db.execute(
            select(TenantMembership).where(
                TenantMembership.user_id == user.id,
                TenantMembership.tenant_id == user.tenant_id,
            )
        )
        membership = result.scalar_one_or_none()

        if not membership or membership.role.value not in self.required_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of: {', '.join(sorted(self.required_roles))}",
            )


class RequireScopes:
    """FastAPI dependency that enforces API key scopes.

    Usage:
        @router.post("/jobs", dependencies=[Depends(RequireScopes("jobs:write"))])
        async def create_job(...): ...

    API keys must have explicit scopes granted. Empty scopes = no access.
    """

    def __init__(self, *required: str):
        self.required = set(required)

    async def __call__(self, api_key: ApiKey = Depends(get_current_api_key)) -> None:
        granted = set(api_key.scopes) if api_key.scopes else set()
        if not granted:
            raise HTTPException(
                status_code=403,
                detail="API key has no scopes granted",
            )

        missing = self.required - granted
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"API key missing required scopes: {', '.join(sorted(missing))}",
            )


async def require_admin_key(
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
) -> None:
    """Validate that the request carries a valid admin key.

    Uses a dedicated ADMIN_KEY setting (falls back to SECRET_KEY in debug mode).
    Comparison is constant-time to prevent timing side-channel attacks.
    """
    if not settings.ADMIN_KEY:
        # validate_settings() blocks this in production (DEBUG=false),
        # but guard here too for defense-in-depth.
        raise HTTPException(status_code=503, detail="Admin key not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.ADMIN_KEY):
        logger.warning("admin_auth_failed")
        raise HTTPException(status_code=401, detail="Invalid admin key")
