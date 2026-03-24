"""OAuth social login endpoints — Google and GitHub.

These endpoints handle the Authorization Code flow:
1. GET  /auth/oauth/providers       — list configured providers
2. GET  /auth/oauth/{provider}/authorize — get authorization URL
3. POST /auth/oauth/{provider}/callback  — exchange code for tokens
4. GET  /auth/oauth/accounts        — list linked OAuth accounts
5. POST /auth/oauth/{provider}/link — initiate account linking
6. DELETE /auth/oauth/{provider}/unlink — remove linked account
"""

import re
import secrets
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_token, get_db
from app.api.rate_limit import RateLimiter
from app.api.schemas_auth import (
    AuthResponse,
    OAuthAccountResponse,
    OAuthAuthorizeResponse,
    OAuthCallbackRequest,
    OAuthProvidersResponse,
    UserResponse,
)
from app.api.v1._auth_helpers import check_mfa_required, get_user_role, issue_tokens_for_user
from app.config import settings
from app.core.events import OAuthAccountLinked, UserRegistered, emit
from app.core.oauth import (
    exchange_code_for_tokens,
    fetch_user_profile,
    generate_authorize_url,
    get_configured_providers,
    validate_state,
    verify_linking_user_id,
)
from app.db.models import OAuthAccount, Tenant, TenantMembership, User, UserRole

router = APIRouter(prefix="/auth/oauth")
logger = structlog.stdlib.get_logger()

_auth_rate_limit = RateLimiter(max_requests=settings.RATE_LIMIT_AUTH_ENDPOINTS, window=60, key_prefix="rl:oauth")

_VALID_PROVIDERS = frozenset({"google", "github"})


def _validate_provider(provider: str) -> str:
    """Validate that provider is a known OAuth provider name."""
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown OAuth provider: {provider}")
    return provider


ValidProvider = Annotated[str, Depends(_validate_provider)]


@router.get("/providers", response_model=OAuthProvidersResponse)
async def list_providers():
    """Return list of configured OAuth providers."""
    return OAuthProvidersResponse(providers=get_configured_providers())


@router.get("/{provider}/authorize", response_model=OAuthAuthorizeResponse, dependencies=[Depends(_auth_rate_limit)])
async def authorize(provider: ValidProvider, request: Request):
    """Get the authorization URL for an OAuth provider."""
    try:
        redirect_uri = f"{settings.APP_BASE_URL}/auth/callback/{provider}"
        url = await generate_authorize_url(provider, redirect_uri)
        return OAuthAuthorizeResponse(url=url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post("/{provider}/callback", response_model=AuthResponse, dependencies=[Depends(_auth_rate_limit)])
async def callback(
    provider: ValidProvider,
    body: OAuthCallbackRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback — exchange code for tokens and sign in/up."""
    # Validate state (CSRF protection)
    state_data = await validate_state(body.state)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    if state_data.get("provider") != provider:
        raise HTTPException(status_code=400, detail="Provider mismatch in OAuth state")

    redirect_uri = state_data["redirect_uri"]

    # Validate redirect_uri matches expected base URL
    if not redirect_uri.startswith(settings.APP_BASE_URL + "/"):
        raise HTTPException(status_code=400, detail="Invalid redirect URI in OAuth state")

    # Exchange code for tokens
    try:
        token_data = await exchange_code_for_tokens(provider, body.code, redirect_uri)
    except Exception:
        logger.exception("oauth_code_exchange_failed", provider=provider)
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code") from None

    access_token_value = token_data.get("access_token")
    if not access_token_value:
        raise HTTPException(status_code=400, detail="No access token in provider response")

    # Fetch user profile
    try:
        profile = await fetch_user_profile(provider, access_token_value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception:
        logger.exception("oauth_profile_fetch_failed", provider=provider)
        raise HTTPException(status_code=400, detail="Failed to fetch user profile from provider") from None

    if not profile.email:
        raise HTTPException(status_code=400, detail="OAuth provider did not return an email address")

    email = profile.email.strip().lower()

    # Check for account linking flow
    linking_user_id = state_data.get("linking_user_id")
    if linking_user_id:
        if not verify_linking_user_id(state_data):
            raise HTTPException(status_code=400, detail="Invalid account linking state")
        return await _handle_account_linking(
            linking_user_id, provider, profile, token_data, db, response,
        )

    # === Sign-in / Sign-up flow ===

    # 1. Check if OAuthAccount already exists (returning user)
    existing_oauth = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == profile.provider_user_id,
        )
    )
    oauth_account = existing_oauth.scalar_one_or_none()

    if oauth_account:
        # Returning user — update tokens and sign in
        user_result = await db.execute(
            select(User).where(User.id == oauth_account.user_id, User.deleted_at.is_(None))
        )
        user = user_result.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled")

        _update_oauth_tokens(oauth_account, token_data)
        user.last_login_at = datetime.now(UTC)

        role = await get_user_role(user, user.tenant_id, db)

        # Check MFA before issuing full tokens
        mfa_result = await check_mfa_required(user, db, role, amr=["oauth"])
        if mfa_result:
            return AuthResponse(
                access_token=mfa_result["mfa_token"],
                expires_in=300,
                mfa_required=True,
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

        access_token, expires_in = await issue_tokens_for_user(user, user.tenant_id, db, response)
        await db.commit()

        logger.info("oauth_login", user_id=str(user.id), provider=provider)

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

    # 2. Check if a User with the same email exists (implicit link)
    existing_user_result = await db.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    existing_user = existing_user_result.scalar_one_or_none()

    if existing_user:
        if not existing_user.is_active:
            raise HTTPException(status_code=403, detail="Account is disabled")

        # Link OAuth account to existing user
        new_oauth = OAuthAccount(
            user_id=existing_user.id,
            provider=provider,
            provider_user_id=profile.provider_user_id,
        )
        _update_oauth_tokens(new_oauth, token_data)
        db.add(new_oauth)

        # Only mark email as verified if the provider verifiably confirmed ownership
        # (Google checks email_verified in fetch_user_profile; GitHub only returns verified emails)
        if not existing_user.email_verified:
            existing_user.email_verified = True
        existing_user.last_login_at = datetime.now(UTC)

        role = await get_user_role(existing_user, existing_user.tenant_id, db)

        # Check MFA before issuing full tokens
        mfa_result = await check_mfa_required(existing_user, db, role, amr=["oauth"])
        if mfa_result:
            return AuthResponse(
                access_token=mfa_result["mfa_token"],
                expires_in=300,
                mfa_required=True,
                user=UserResponse(
                    id=existing_user.id,
                    email=existing_user.email,
                    display_name=existing_user.display_name,
                    email_verified=existing_user.email_verified,
                    is_active=existing_user.is_active,
                    tenant_id=existing_user.tenant_id,
                    role=role,
                    created_at=existing_user.created_at,
                ),
            )

        access_token, expires_in = await issue_tokens_for_user(
            existing_user, existing_user.tenant_id, db, response,
        )
        await db.commit()

        await emit(OAuthAccountLinked(
            user_id=str(existing_user.id),
            provider=provider,
            email=email,
        ))

        logger.info("oauth_implicit_link", user_id=str(existing_user.id), provider=provider)

        return AuthResponse(
            access_token=access_token,
            expires_in=expires_in,
            user=UserResponse(
                id=existing_user.id,
                email=existing_user.email,
                display_name=existing_user.display_name,
                email_verified=existing_user.email_verified,
                is_active=existing_user.is_active,
                tenant_id=existing_user.tenant_id,
                role=role,
                created_at=existing_user.created_at,
            ),
        )

    # 3. New user — create account, tenant, and membership
    tenant_slug = _generate_tenant_slug(email)

    # Handle slug collision — ensure uniqueness with random suffix
    slug_found = False
    for _ in range(5):
        existing_tenant = await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
        if not existing_tenant.scalar_one_or_none():
            slug_found = True
            break
        tenant_slug = f"{_generate_tenant_slug(email)}-{secrets.token_hex(3)}"
    if not slug_found:
        raise HTTPException(status_code=500, detail="Failed to generate unique tenant identifier")

    tenant = Tenant(name=tenant_slug, slug=tenant_slug)
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=None,
        display_name=profile.display_name or email.split("@")[0],
        email_verified=True,
    )
    db.add(user)
    await db.flush()

    membership = TenantMembership(tenant_id=tenant.id, user_id=user.id, role=UserRole.OWNER)
    db.add(membership)

    new_oauth = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_user_id=profile.provider_user_id,
    )
    _update_oauth_tokens(new_oauth, token_data)
    db.add(new_oauth)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Race condition: another request created the user concurrently.
        # Re-fetch and sign in instead of returning a 409 error.
        existing_oauth_retry = await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_user_id == profile.provider_user_id,
            )
        )
        retry_oauth = existing_oauth_retry.scalar_one_or_none()
        if retry_oauth:
            retry_user_result = await db.execute(
                select(User).where(User.id == retry_oauth.user_id, User.deleted_at.is_(None))
            )
            retry_user = retry_user_result.scalar_one_or_none()
            if retry_user and retry_user.is_active:
                retry_user.last_login_at = datetime.now(UTC)
                access_token, expires_in = await issue_tokens_for_user(
                    retry_user, retry_user.tenant_id, db, response,
                )
                await db.commit()
                role = await get_user_role(retry_user, retry_user.tenant_id, db)
                return AuthResponse(
                    access_token=access_token,
                    expires_in=expires_in,
                    user=UserResponse(
                        id=retry_user.id,
                        email=retry_user.email,
                        display_name=retry_user.display_name,
                        email_verified=retry_user.email_verified,
                        is_active=retry_user.is_active,
                        tenant_id=retry_user.tenant_id,
                        role=role,
                        created_at=retry_user.created_at,
                    ),
                )
        raise HTTPException(status_code=409, detail="Account could not be created — email or provider conflict") from None

    await db.refresh(user)

    # Issue tokens only after successful commit to avoid stale cookies on rollback
    access_token, expires_in = await issue_tokens_for_user(user, tenant.id, db, response)
    await db.commit()

    await emit(UserRegistered(user_id=str(user.id), email=email, tenant_id=str(tenant.id)))
    await emit(OAuthAccountLinked(user_id=str(user.id), provider=provider, email=email))

    logger.info("oauth_register", user_id=str(user.id), provider=provider, tenant_id=str(tenant.id))

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
            role=UserRole.OWNER.value,
            created_at=user.created_at,
        ),
    )


@router.get("/accounts", response_model=list[OAuthAccountResponse])
async def list_oauth_accounts(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's linked OAuth accounts."""
    result = await db.execute(
        select(OAuthAccount).where(OAuthAccount.user_id == user.id)
    )
    return result.scalars().all()


@router.post("/{provider}/link", response_model=OAuthAuthorizeResponse, dependencies=[Depends(_auth_rate_limit)])
async def link_provider(
    provider: ValidProvider,
    user: User = Depends(get_current_user_from_token),
):
    """Initiate OAuth account linking for the current user."""
    # Check if already linked
    try:
        redirect_uri = f"{settings.APP_BASE_URL}/auth/callback/{provider}"
        url = await generate_authorize_url(provider, redirect_uri, linking_user_id=str(user.id))
        return OAuthAuthorizeResponse(url=url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.delete("/{provider}/unlink", dependencies=[Depends(_auth_rate_limit)])
async def unlink_provider(
    provider: ValidProvider,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Remove a linked OAuth account. Cannot remove last auth method."""
    # Lock the user's OAuth accounts to prevent TOCTOU race on concurrent unlinks
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id,
            OAuthAccount.provider == provider,
        ).with_for_update()
    )
    oauth_account = result.scalar_one_or_none()
    if not oauth_account:
        raise HTTPException(status_code=404, detail="OAuth account not found")

    # Check user retains at least one auth method (under lock)
    other_oauth_result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id,
            OAuthAccount.provider != provider,
        ).with_for_update()
    )
    has_other_oauth = other_oauth_result.scalar_one_or_none() is not None
    has_password = user.password_hash is not None

    if not has_other_oauth and not has_password:
        raise HTTPException(
            status_code=400,
            detail="Cannot unlink — this is your only authentication method. Set a password first.",
        )

    await db.delete(oauth_account)
    await db.commit()

    logger.info("oauth_unlinked", user_id=str(user.id), provider=provider)
    return {"detail": f"{provider} account unlinked"}


async def _handle_account_linking(
    linking_user_id: str,
    provider: str,
    profile,
    token_data: dict,
    db: AsyncSession,
    response: Response,
) -> AuthResponse:
    """Handle the account linking flow (user explicitly linking a provider)."""
    import uuid

    user_result = await db.execute(
        select(User).where(User.id == uuid.UUID(linking_user_id), User.deleted_at.is_(None))
    )
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    # Check if this provider account is already linked to another user
    existing_oauth = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == profile.provider_user_id,
        )
    )
    if existing_oauth.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This provider account is already linked to another user")

    new_oauth = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_user_id=profile.provider_user_id,
    )
    _update_oauth_tokens(new_oauth, token_data)
    db.add(new_oauth)

    access_token, expires_in = await issue_tokens_for_user(user, user.tenant_id, db, response)
    await db.commit()

    await emit(OAuthAccountLinked(
        user_id=str(user.id),
        provider=provider,
        email=profile.email,
    ))

    role = await get_user_role(user, user.tenant_id, db)
    logger.info("oauth_account_linked", user_id=str(user.id), provider=provider)

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


def _update_oauth_tokens(oauth_account: OAuthAccount, token_data: dict) -> None:
    """Update encrypted tokens on an OAuthAccount."""
    if token_data.get("access_token"):
        oauth_account.set_access_token(token_data["access_token"])
    if token_data.get("refresh_token"):
        oauth_account.set_refresh_token(token_data["refresh_token"])


def _generate_tenant_slug(email: str) -> str:
    """Generate a tenant slug from an email address."""
    prefix = email.split("@")[0]
    # Sanitize: lowercase, replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")
    # Ensure minimum length
    if len(slug) < 2:
        slug = f"{slug}-org"
    # Ensure it matches the pattern: starts and ends with alphanumeric
    if not re.match(r"^[a-z0-9]", slug):
        slug = f"u-{slug}"
    if not re.search(r"[a-z0-9]$", slug):
        slug = f"{slug}-0"
    return slug[:63]  # Max 63 chars
