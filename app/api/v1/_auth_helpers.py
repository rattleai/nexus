"""Shared authentication helpers used by auth_routes and oauth_social."""

from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.db.models import RefreshToken, Tenant, TenantMembership, User

_REFRESH_COOKIE = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"
MAX_REFRESH_TOKENS_PER_USER = 10


def set_refresh_cookie(response: Response, raw_token: str) -> None:
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


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, path=_REFRESH_COOKIE_PATH)


async def issue_tokens_for_user(
    user: User,
    tenant_id,
    db: AsyncSession,
    response: Response,
) -> tuple[str, int]:
    """Issue access + refresh tokens for a user and set the refresh cookie.

    Returns (access_token, expires_in).
    """
    # Revoke oldest tokens if exceeding limit
    existing_tokens = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
        .order_by(RefreshToken.created_at.asc())
    )
    active_tokens = existing_tokens.scalars().all()
    if len(active_tokens) >= MAX_REFRESH_TOKENS_PER_USER:
        for old_token in active_tokens[: len(active_tokens) - MAX_REFRESH_TOKENS_PER_USER + 1]:
            old_token.revoked = True

    # Create refresh token
    raw_refresh, refresh_hash = create_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)

    access_token = create_access_token({"sub": str(user.id), "tenant_id": str(tenant_id)})
    set_refresh_cookie(response, raw_refresh)

    expires_in = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return access_token, expires_in


async def check_mfa_required(
    user: User,
    db: AsyncSession,
    role: str | None,
    amr: list[str] | None = None,
) -> dict | None:
    """Check if MFA is required for the user. Returns MFA-pending response dict or None.

    If MFA is required and the user has WebAuthn credentials, returns a dict
    with {mfa_token, user} for the caller to build the response. Otherwise None.
    """
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    login_tenant = tenant_result.scalar_one_or_none()
    tenant_requires_mfa = (login_tenant and login_tenant.settings or {}).get("require_mfa", False)

    if not (getattr(user, "mfa_enabled", False) or tenant_requires_mfa):
        return None

    from app.db.models.mobile import WebAuthnCredential

    cred_result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id).limit(1)
    )
    has_webauthn = cred_result.scalar_one_or_none() is not None

    if not has_webauthn:
        return None

    await db.commit()
    mfa_token = create_access_token(
        {
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "type": "mfa_pending",
            "amr": amr or ["pwd"],
        },
        expires_delta=timedelta(minutes=5),
    )
    return {"mfa_token": mfa_token, "user": user, "role": role}


async def get_user_role(user: User, tenant_id, db: AsyncSession) -> str | None:
    """Get a user's role within a tenant."""
    membership = await db.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user.id,
            TenantMembership.tenant_id == tenant_id,
        )
    )
    member = membership.scalar_one_or_none()
    return member.role.value if member else None
