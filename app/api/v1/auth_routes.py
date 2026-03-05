"""Authentication endpoints — register, login, refresh, logout, profile.

These endpoints are only active when AUTH_ENABLED=true.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_token, get_db
from app.api.rate_limit import RateLimiter
from app.api.schemas_auth import AuthResponse, TokenResponse, UserLogin, UserRegister, UserResponse
from app.config import settings

_auth_rate_limit = RateLimiter(max_requests=settings.RATE_LIMIT_AUTH_ENDPOINTS, window=60, key_prefix="rl:auth")
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.models import RefreshToken, Tenant, TenantMembership, User, UserRole

router = APIRouter(prefix="/auth")
logger = structlog.stdlib.get_logger()

_REFRESH_COOKIE = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    """Set the refresh token as an httpOnly cookie."""
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=raw_token,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="lax",
        path=_REFRESH_COOKIE_PATH,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, path=_REFRESH_COOKIE_PATH)


@router.post("/register", response_model=AuthResponse, status_code=201, dependencies=[Depends(_auth_rate_limit)])
async def register(body: UserRegister, response: Response, db: AsyncSession = Depends(get_db)):
    # Check for existing user
    existing = await db.execute(
        select(User).where(User.email == body.email, User.deleted_at.is_(None))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Resolve or create tenant
    if body.tenant_slug:
        existing_tenant = await db.execute(select(Tenant).where(Tenant.slug == body.tenant_slug))
        if existing_tenant.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Tenant slug already taken")
        tenant = Tenant(name=body.tenant_slug, slug=body.tenant_slug)
        db.add(tenant)
        await db.flush()
        role = UserRole.OWNER
    else:
        raise HTTPException(status_code=422, detail="tenant_slug is required for registration")

    # Create user
    user = User(
        tenant_id=tenant.id,
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
    await db.flush()

    # Create membership
    membership = TenantMembership(tenant_id=tenant.id, user_id=user.id, role=role)
    db.add(membership)

    # Create refresh token
    raw_refresh, refresh_hash = create_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)

    await db.commit()
    await db.refresh(user)

    # Create access token
    access_token = create_access_token({"sub": str(user.id), "tenant_id": str(tenant.id)})
    _set_refresh_cookie(response, raw_refresh)

    logger.info("user_registered", user_id=str(user.id), tenant_id=str(tenant.id))

    expires_in = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return AuthResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            email_verified=user.email_verified,
            is_active=user.is_active,
            tenant_id=user.tenant_id,
            role=role.value,
            created_at=user.created_at,
        ),
    )


@router.post("/login", response_model=AuthResponse, dependencies=[Depends(_auth_rate_limit)])
async def login(body: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.email == body.email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    # Update last login
    user.last_login_at = datetime.now(UTC)

    # Get role
    membership = await db.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user.id, TenantMembership.tenant_id == user.tenant_id
        )
    )
    member = membership.scalar_one_or_none()
    role = member.role.value if member else None

    # Create refresh token
    raw_refresh, refresh_hash = create_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)
    await db.commit()

    access_token = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
    _set_refresh_cookie(response, raw_refresh)

    logger.info("user_logged_in", user_id=str(user.id))

    expires_in = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return AuthResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            email_verified=user.email_verified,
            is_active=user.is_active,
            tenant_id=user.tenant_id,
            role=role,
            created_at=user.created_at,
        ),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
        )
    )
    rt = result.scalar_one_or_none()

    if not rt or rt.expires_at < datetime.now(UTC):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Revoke old token
    rt.revoked = True

    # Load user
    user_result = await db.execute(select(User).where(User.id == rt.user_id, User.deleted_at.is_(None)))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Issue new refresh token (rotation)
    raw_refresh, refresh_hash = create_refresh_token()
    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(new_rt)
    await db.commit()

    access_token = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
    _set_refresh_cookie(response, raw_refresh)

    return TokenResponse(
        access_token=access_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        rt = result.scalar_one_or_none()
        if rt:
            rt.revoked = True
            await db.commit()

    _clear_refresh_cookie(response)
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Get the current authenticated user's profile. Requires JWT Bearer token."""
    # Get role from membership
    membership = await db.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user.id,
            TenantMembership.tenant_id == user.tenant_id,
        )
    )
    member = membership.scalar_one_or_none()
    role = member.role.value if member else None

    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified,
        is_active=user.is_active,
        tenant_id=user.tenant_id,
        role=role,
        created_at=user.created_at,
    )
