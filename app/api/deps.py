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
    request: Request,
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Resolve and validate the API key from the request header.

    Stores the resolved key on request.state.api_key for downstream
    dependencies (e.g. ApiKeyRateLimiter).
    """
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

    # Store on request state for ApiKeyRateLimiter
    request.state.api_key = api_key

    return api_key


async def get_current_api_key_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiKey | None:
    """Resolve the API key if present, or return None for JWT-authenticated users.

    Use this instead of get_current_api_key in endpoints that support both
    JWT and API key authentication.
    """
    return await _resolve_api_key(request, db)


async def _resolve_api_key(request: Request, db: AsyncSession) -> ApiKey | None:
    """Try to resolve an API key from the X-API-Key header. Returns None if absent."""
    x_api_key = request.headers.get("X-API-Key")
    if not x_api_key:
        return None

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

    request.state.api_key = api_key
    return api_key


async def _resolve_user_from_jwt(request: Request, db: AsyncSession) -> User | None:
    """Try to resolve a user from a JWT Bearer token. Returns None if absent."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    from app.core.security import decode_access_token, is_token_revoked, is_user_token_revoked

    token = auth_header[7:]
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token") from None

    jti = payload.get("jti")
    if jti and await is_token_revoked(jti):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    iat = payload.get("iat")
    if user_id_str and iat and await is_user_token_revoked(user_id_str, int(iat)):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid token payload") from None

    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    jwt_tenant_id = payload.get("tenant_id")
    if jwt_tenant_id and str(user.tenant_id) != str(jwt_tenant_id):
        raise HTTPException(status_code=401, detail="Token tenant mismatch — please re-authenticate")

    return user


async def get_current_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Return the tenant for the current request.

    Accepts either a JWT Bearer token or an X-API-Key header.
    JWT is checked first; if absent, falls back to API key.
    Also sets PostgreSQL RLS tenant context for defense-in-depth isolation.
    """
    # Try JWT auth first (frontend users)
    user = await _resolve_user_from_jwt(request, db)
    if user:
        result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id, Tenant.is_active.is_(True)))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=403, detail="Tenant not found or inactive")
        await set_tenant_context(db, str(tenant.id))
        return tenant

    # Fall back to API key auth
    api_key = await _resolve_api_key(request, db)
    if api_key:
        tenant = api_key.tenant
        await set_tenant_context(db, str(tenant.id))
        return tenant

    raise HTTPException(status_code=401, detail="Authentication required (Bearer token or X-API-Key)")


async def get_tenant_db(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> AsyncSession:
    """Get a DB session with RLS tenant context already set.

    Use this instead of manually calling set_tenant_context() in every endpoint.
    The tenant context is guaranteed to be set before the session is returned.
    """
    await set_tenant_context(db, str(tenant.id))
    return db


# ── JWT auth (new, opt-in via AUTH_ENABLED) ──────────────


async def get_current_user_from_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT Bearer token, return the authenticated user.

    Raises 401 if the token is missing, expired, or invalid.
    """
    from app.core.security import decode_access_token, is_token_revoked, is_user_token_revoked

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

    # Check token revocation blacklist (P0-7: JWT revocation)
    jti = payload.get("jti")
    if jti and await is_token_revoked(jti):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Check if all user tokens were bulk-revoked (e.g. after password reset)
    iat = payload.get("iat")
    if user_id_str and iat and await is_user_token_revoked(user_id_str, int(iat)):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    try:
        user_id = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid token payload") from None

    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Cross-check JWT tenant_id against the user's current tenant to detect
    # stale tokens (e.g. user was moved to a different tenant after JWT was issued).
    jwt_tenant_id = payload.get("tenant_id")
    if jwt_tenant_id and str(user.tenant_id) != str(jwt_tenant_id):
        raise HTTPException(status_code=401, detail="Token tenant mismatch — please re-authenticate")

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
                detail="Insufficient permissions",
            )


class RequireUI:
    """Reject API key / OAuth client auth — endpoint is only accessible via JWT.

    Apply this to critical infrastructure endpoints that must never be
    accessible programmatically (API key management, OAuth clients, audit
    logs, etc.).  This prevents privilege-escalation attacks where an API
    key creates new keys with broader scopes.

    Usage:
        @router.get("/api-keys", dependencies=[Depends(RequireUI())])
        async def list_api_keys(...): ...
    """

    async def __call__(
        self,
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> User:
        # Only JWT Bearer tokens (i.e. browser / UI sessions) are accepted
        user = await _resolve_user_from_jwt(request, db)
        if not user:
            raise HTTPException(
                status_code=403,
                detail="This endpoint is only accessible from the application UI",
            )
        return user


class RequireScopes:
    """FastAPI dependency that enforces API key scopes.

    Usage:
        @router.post("/jobs", dependencies=[Depends(RequireScopes("jobs:write"))])
        async def create_job(...): ...

    API keys must have explicit scopes granted. Empty scopes = no access.
    JWT-authenticated users bypass scope checks (scopes are an API-key concept).
    """

    def __init__(self, *required: str):
        self.required = set(required)

    async def __call__(self, request: Request, db: AsyncSession = Depends(get_db)) -> None:
        # JWT-authenticated users bypass API key scope checks
        user = await _resolve_user_from_jwt(request, db)
        if user:
            return

        # For API key auth, enforce scopes
        api_key = await _resolve_api_key(request, db)
        if not api_key:
            raise HTTPException(status_code=401, detail="Authentication required")

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
                detail="Insufficient API key permissions",
            )


# ── OAuth Client Credentials auth ──────────────────────


async def get_tenant_from_client_credentials(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Authenticate via OAuth Client Credentials JWT (Bearer token).

    Validates the token was issued by the Client Credentials flow,
    resolves the tenant, and sets RLS context.
    """
    from app.core.security import _get_effective_algorithm, _get_jwt_verification_key, is_token_revoked

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[7:]
    algorithm = _get_effective_algorithm()
    try:
        payload = jwt.decode(
            token,
            _get_jwt_verification_key(),
            algorithms=[algorithm],
            audience="cadprice-api",
            issuer="cadprice",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token") from None

    if payload.get("type") != "client_credentials":
        raise HTTPException(status_code=401, detail="Invalid token type")

    # Check token revocation blacklist
    jti = payload.get("jti")
    if jti and await is_token_revoked(jti):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    tenant_id_str = payload.get("tenant_id")
    if not tenant_id_str:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    try:
        tenant_id = uuid.UUID(tenant_id_str)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=401, detail="Invalid token payload") from None

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id, Tenant.is_active.is_(True)))
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=401, detail="Tenant not found or inactive")

    # Propagate client scopes for downstream RequireScopes checks
    request.state.client_scopes = payload.get("scopes", [])

    await set_tenant_context(db, str(tenant.id))
    return tenant


async def require_admin_key(
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
) -> None:
    """Validate that the request carries a valid admin key.

    Uses a dedicated ADMIN_KEY setting. Rejects requests when ADMIN_KEY is not configured.
    Comparison is constant-time to prevent timing side-channel attacks.
    """
    if not settings.ADMIN_KEY:
        # validate_settings() blocks this in production (DEBUG=false),
        # but guard here too for defense-in-depth.
        raise HTTPException(status_code=503, detail="Admin key not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.ADMIN_KEY):
        logger.warning("admin_auth_failed")
        raise HTTPException(status_code=401, detail="Invalid admin key")
