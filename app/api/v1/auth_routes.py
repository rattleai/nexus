"""Authentication endpoints — register, login, refresh, logout, profile,
email verification, password reset, and invitation acceptance.

These endpoints are only active when AUTH_ENABLED=true.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_token, get_db
from app.api.rate_limit import RateLimiter
from app.api.schemas_auth import AuthResponse, RegisterResponse, TokenResponse, UserLogin, UserRegister, UserResponse
from app.config import settings
from app.core.email import EmailTemplate, send_email
from app.core.events import InvitationAccepted, UserRegistered, emit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    generate_secure_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from app.db.models import (
    EmailVerificationToken,
    Invitation,
    InvitationStatus,
    RefreshToken,
    Tenant,
    TenantMembership,
    User,
    UserRole,
)

from app.api.v1._auth_helpers import (
    MAX_REFRESH_TOKENS_PER_USER as _MAX_REFRESH_TOKENS_PER_USER,
    clear_refresh_cookie as _clear_refresh_cookie,
    set_refresh_cookie as _set_refresh_cookie,
)

_auth_rate_limit = RateLimiter(max_requests=settings.RATE_LIMIT_AUTH_ENDPOINTS, window=60, key_prefix="rl:auth")
_refresh_rate_limit = RateLimiter(max_requests=30, window=60, key_prefix="rl:auth-refresh")

router = APIRouter(prefix="/auth")
logger = structlog.stdlib.get_logger()

_REFRESH_COOKIE = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 900  # 15 minutes


async def _check_account_lockout(email: str) -> None:
    """Check if an account is locked out due to too many failed login attempts."""
    try:
        from app.core.redis import redis_pool
        key = f"lockout:{email}"
        attempts = await redis_pool.get(key)
        if attempts and int(attempts) >= _MAX_LOGIN_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail="Account temporarily locked due to too many failed login attempts. Try again later.",
            )
    except HTTPException:
        raise
    except Exception:
        pass  # Redis unavailable — fail open (rate limiter still applies)


async def _record_failed_login(email: str, client_ip: str) -> None:
    """Record a failed login attempt for lockout tracking."""
    logger.warning("login_failed", email=email, client_ip=client_ip)
    try:
        from app.core.redis import redis_pool
        key = f"lockout:{email}"
        pipe = redis_pool.pipeline()
        pipe.incr(key)
        pipe.expire(key, _LOGIN_LOCKOUT_SECONDS)
        await pipe.execute()
    except Exception:
        pass  # Redis unavailable — fail open


async def _clear_login_attempts(email: str) -> None:
    """Clear login attempt counter on successful login."""
    try:
        from app.core.redis import redis_pool
        await redis_pool.delete(f"lockout:{email}")
    except Exception:
        pass


@router.post("/register", response_model=RegisterResponse, status_code=201, dependencies=[Depends(_auth_rate_limit)])
async def register(body: UserRegister, db: AsyncSession = Depends(get_db)):
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

    # Create email verification token in same transaction
    raw_verify_token, verify_hash = generate_secure_token()
    verification = EmailVerificationToken(
        user_id=user.id,
        token_hash=verify_hash,
        token_type="email_verification",
        expires_at=datetime.now(UTC) + timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS),
    )
    db.add(verification)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email or tenant slug already taken") from None
    await db.refresh(user)

    # Do NOT issue access/refresh tokens here — the user must verify their
    # email first, then log in.  Issuing tokens pre-verification allows
    # unauthenticated API access with an unverified email address.

    # Send verification email AFTER commit — never hold DB locks during
    # external I/O (email service could hang and deadlock other requests).
    verify_url = f"{settings.APP_BASE_URL}/verify-email?token={raw_verify_token}"
    await send_email(
        to=user.email,
        template=EmailTemplate.VERIFY_EMAIL,
        context={"display_name": user.display_name or user.email, "verify_url": verify_url},
    )
    await emit(UserRegistered(user_id=str(user.id), email=user.email, tenant_id=str(tenant.id)))

    logger.info("user_registered", user_id=str(user.id), tenant_id=str(tenant.id))

    return RegisterResponse(
        message="Registration successful. Please check your email to verify your account.",
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
async def login(body: UserLogin, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"

    # Check account lockout before expensive password verification
    await _check_account_lockout(body.email)

    result = await db.execute(
        select(User).where(User.email == body.email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    # Always run verify_password to prevent timing attacks that reveal whether an email exists
    _dummy_hash = "$2b$12$LJ3m4ys3Lg2RqFONxLwAyOSJjGxTPiOVGP6XB7mT7lNH3.WIOQWGK"
    stored_hash = user.password_hash if (user and user.password_hash) else _dummy_hash
    password_valid = verify_password(body.password, stored_hash)

    if not user or not user.password_hash or not password_valid:
        await _record_failed_login(body.email, client_ip)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        logger.warning("login_inactive_account", email=body.email, client_ip=client_ip)
        raise HTTPException(status_code=403, detail="Account is disabled")

    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Email not verified. Please check your inbox.")

    # Clear lockout counter on successful login
    await _clear_login_attempts(body.email)

    # Auto-rehash legacy bcrypt passwords to argon2id on successful login
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

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

    # Check if MFA is required
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    login_tenant = tenant_result.scalar_one_or_none()
    tenant_requires_mfa = (login_tenant and login_tenant.settings or {}).get("require_mfa", False)

    if (getattr(user, "mfa_enabled", False) or tenant_requires_mfa):
        # Check if user has WebAuthn credentials
        from app.db.models.mobile import WebAuthnCredential
        cred_result = await db.execute(
            select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id).limit(1)
        )
        has_webauthn = cred_result.scalar_one_or_none() is not None

        if has_webauthn:
            await db.commit()
            # Issue MFA-pending token (5 minute TTL)
            mfa_token = create_access_token(
                {
                    "sub": str(user.id),
                    "tenant_id": str(user.tenant_id),
                    "type": "mfa_pending",
                    "amr": ["pwd"],
                },
                expires_delta=timedelta(minutes=5),
            )
            return AuthResponse(
                access_token=mfa_token,
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

    # Revoke oldest tokens if exceeding limit
    existing_tokens = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
        .order_by(RefreshToken.created_at.asc())
    )
    active_tokens = existing_tokens.scalars().all()
    if len(active_tokens) >= _MAX_REFRESH_TOKENS_PER_USER:
        for old_token in active_tokens[: len(active_tokens) - _MAX_REFRESH_TOKENS_PER_USER + 1]:
            old_token.revoked = True

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

    logger.info("user_logged_in", user_id=str(user.id), client_ip=client_ip)

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


_REFRESH_GRACE_SECONDS = 30  # Allow replay of recently-revoked token (lost response recovery)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(_refresh_rate_limit)])
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

    # Atomic compare-and-swap: only revoke if not already revoked
    revoke_result = await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked.is_(False),
        )
        .values(revoked=True)
        .returning(RefreshToken.id, RefreshToken.user_id, RefreshToken.expires_at)
    )
    row = revoke_result.first()

    if not row:
        # Token not found or already revoked.
        # Grace period: if the previous refresh response was lost in transit,
        # the client still holds the old (now revoked) cookie. Allow recovery
        # by checking if this token was very recently consumed and a replacement exists.
        row = await _try_grace_period_refresh(token_hash, db)
        if not row:
            _clear_refresh_cookie(response)
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    if row.expires_at < datetime.now(UTC):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Load user
    user_result = await db.execute(select(User).where(User.id == row.user_id, User.deleted_at.is_(None)))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active or not user.email_verified:
        await db.commit()
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Issue new refresh token
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


async def _try_grace_period_refresh(token_hash: str, db: AsyncSession):
    """Handle the case where a refresh token was consumed but the response was lost.

    If the revoked token has a recently-created replacement (within grace window),
    consume the replacement and return its row so the caller can re-issue tokens.
    This prevents permanent logout when a refresh response is lost in transit.
    """
    # Look up the revoked token
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    revoked_token = result.scalar_one_or_none()

    if not revoked_token or revoked_token.expires_at < datetime.now(UTC):
        return None

    # Only allow grace period if the token was revoked very recently
    # (created_at of a newer token for this user is within the grace window)
    grace_cutoff = datetime.now(UTC) - timedelta(seconds=_REFRESH_GRACE_SECONDS)
    replacement_result = await db.execute(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == revoked_token.user_id,
            RefreshToken.revoked.is_(False),
            RefreshToken.created_at >= grace_cutoff,
        )
        .order_by(RefreshToken.created_at.desc())
        .limit(1)
    )
    replacement = replacement_result.scalar_one_or_none()

    if not replacement:
        return None

    # Consume the replacement token (it was never delivered to the client)
    replacement.revoked = True
    logger.info(
        "refresh_token_grace_period_used",
        user_id=str(revoked_token.user_id),
        original_token_id=str(revoked_token.id),
        replacement_token_id=str(replacement.id),
    )

    # Return a row-like object matching what the caller expects
    return type("Row", (), {
        "id": replacement.id,
        "user_id": replacement.user_id,
        "expires_at": replacement.expires_at,
    })()


@router.post("/logout", dependencies=[Depends(_auth_rate_limit)])
async def logout(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Revoke refresh token in DB
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        rt = result.scalar_one_or_none()
        if rt:
            rt.revoked = True
            await db.commit()

    # Revoke current access token via Redis blacklist
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from app.core.security import decode_access_token, revoke_access_token
            payload = decode_access_token(auth_header[7:])
            jti = payload.get("jti")
            if jti:
                await revoke_access_token(jti)
        except Exception:
            pass  # Token may already be invalid — proceed with logout

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


# ── Profile update ──────────────────────────────────────


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=255)
    locale: str | None = Field(None, min_length=2, max_length=10)


@router.patch("/me", response_model=UserResponse)
async def update_current_user_profile(
    body: UpdateProfileRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's profile."""
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No fields to update")

    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

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


# ── Change password ────────────────────────────────────


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


@router.post("/change-password", dependencies=[Depends(_auth_rate_limit)])
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    await db.commit()

    return {"message": "Password changed successfully"}


# ── Resend email verification ──────────────────────────


@router.post("/resend-verification", dependencies=[Depends(_auth_rate_limit)])
async def resend_email_verification(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Resend the email verification token."""
    if user.email_verified:
        return {"message": "Email is already verified"}

    from app.db.models.auth import EmailVerificationToken

    raw_token, token_hash = generate_secure_token()

    verification = EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(verification)
    await db.commit()

    verify_url = f"{settings.APP_BASE_URL}/verify-email?token={raw_token}"
    await send_email(
        to=user.email,
        template=EmailTemplate.EMAIL_VERIFICATION,
        context={"display_name": user.display_name or user.email, "verify_url": verify_url},
    )

    return {"message": "Verification email sent"}


# ── Email verification ──────────────────────────────────


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)


@router.post("/verify-email", dependencies=[Depends(_auth_rate_limit)])
async def verify_email(body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    """Verify a user's email address using the token sent to their email."""
    token_hash = hash_token(body.token)
    now = datetime.now(UTC)

    # Atomic claim: UPDATE ... WHERE used_at IS NULL prevents race conditions
    claim_result = await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.token_type == "email_verification",
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at >= now,
        )
        .values(used_at=now)
        .returning(EmailVerificationToken.user_id)
    )
    claimed = claim_result.first()
    if not claimed:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    # Verify user's email (exclude soft-deleted users)
    user_result = await db.execute(
        select(User).where(User.id == claimed.user_id, User.deleted_at.is_(None))
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.email_verified = True
    await db.commit()

    logger.info("email_verified", user_id=str(user.id))
    return {"status": "verified", "message": "Email address verified successfully."}


# ── Password reset ───────────────────────────────────────


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        from app.api.schemas_auth import _validate_password_strength
        return _validate_password_strength(v)


@router.post("/forgot-password", dependencies=[Depends(_auth_rate_limit)])
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Request a password reset email. Always returns success to prevent email enumeration."""
    result = await db.execute(
        select(User).where(User.email == body.email.strip().lower(), User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if user:
        # Invalidate any previous unused reset tokens for this user
        await db.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.token_type == "password_reset",
                EmailVerificationToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )

        raw_token, token_hash_val = generate_secure_token()
        reset_token = EmailVerificationToken(
            user_id=user.id,
            token_hash=token_hash_val,
            token_type="password_reset",
            expires_at=datetime.now(UTC) + timedelta(hours=settings.PASSWORD_RESET_EXPIRE_HOURS),
        )
        db.add(reset_token)
        await db.commit()

        reset_url = f"{settings.APP_BASE_URL}/reset-password?token={raw_token}"
        await send_email(
            to=user.email,
            template=EmailTemplate.PASSWORD_RESET,
            context={"display_name": user.display_name or user.email, "reset_url": reset_url},
        )
        logger.info("password_reset_requested", user_id=str(user.id))

    # Always return success to prevent email enumeration
    return {"status": "sent", "message": "If an account exists with that email, a reset link has been sent."}


@router.post("/reset-password", dependencies=[Depends(_auth_rate_limit)])
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Reset password using the token from the reset email."""
    token_hash_val = hash_token(body.token)

    # Atomic claim: UPDATE ... WHERE used_at IS NULL prevents race conditions
    # where concurrent requests could both use the same reset token.
    now = datetime.now(UTC)
    claim_result = await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.token_hash == token_hash_val,
            EmailVerificationToken.token_type == "password_reset",
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at >= now,
        )
        .values(used_at=now)
        .returning(EmailVerificationToken.user_id)
    )
    claimed = claim_result.first()
    if not claimed:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user_result = await db.execute(
        select(User).where(User.id == claimed.user_id, User.deleted_at.is_(None))
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(body.new_password)

    # Revoke all existing refresh tokens to invalidate sessions after password reset
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )

    await db.commit()

    # Revoke all outstanding access tokens for this user via Redis blacklist
    from app.core.security import revoke_all_user_tokens
    await revoke_all_user_tokens(str(user.id))

    logger.info("password_reset_completed", user_id=str(user.id))
    return {"status": "reset", "message": "Password has been reset successfully."}


# ── Invitation acceptance ────────────────────────────────


class AcceptInvitationRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.api.schemas_auth import _validate_password_strength
        return _validate_password_strength(v)


@router.post("/accept-invitation", response_model=AuthResponse, dependencies=[Depends(_auth_rate_limit)])
async def accept_invitation(
    body: AcceptInvitationRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Accept a team invitation. Creates a new user if needed, or adds existing user to tenant."""
    token_hash_val = hash_token(body.token)
    now = datetime.now(UTC)

    # Atomic claim: UPDATE ... WHERE status='PENDING' prevents race conditions
    claim_result = await db.execute(
        update(Invitation)
        .where(
            Invitation.token_hash == token_hash_val,
            Invitation.status == InvitationStatus.PENDING,
            Invitation.expires_at >= now,
        )
        .values(status=InvitationStatus.ACCEPTED, accepted_at=now)
        .returning(Invitation.id, Invitation.email, Invitation.tenant_id, Invitation.role, Invitation.expires_at)
    )
    claimed = claim_result.first()
    if not claimed:
        raise HTTPException(status_code=400, detail="Invalid or expired invitation")

    # Build an invitation-like object from the claimed row for downstream use
    invitation = claimed

    # Defense-in-depth: reject owner role in invitation acceptance
    if invitation.role == UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Cannot assign owner role via invitation")

    # Check if user already exists
    user_result = await db.execute(
        select(User).where(User.email == invitation.email, User.deleted_at.is_(None))
    )
    user = user_result.scalar_one_or_none()

    if user:
        # Existing user — require password to prove account ownership.
        # Without this, anyone who intercepts an invitation token could add
        # an arbitrary existing user to their tenant.
        if not body.password:
            raise HTTPException(
                status_code=422,
                detail="Password is required to verify your identity when joining a new tenant",
            )
        if not user.password_hash or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid password")

        # Check not already a member
        existing_member = await db.execute(
            select(TenantMembership).where(
                TenantMembership.user_id == user.id,
                TenantMembership.tenant_id == invitation.tenant_id,
            )
        )
        if existing_member.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Already a member of this tenant")
    else:
        # New user — password required
        if not body.password:
            raise HTTPException(status_code=422, detail="Password is required for new accounts")

        user = User(
            tenant_id=invitation.tenant_id,
            email=invitation.email,
            password_hash=hash_password(body.password),
            display_name=body.display_name or invitation.email.split("@")[0],
            email_verified=True,  # Verified via invitation email
        )
        db.add(user)
        await db.flush()

    # Create membership
    membership = TenantMembership(
        tenant_id=invitation.tenant_id,
        user_id=user.id,
        role=invitation.role,
    )
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

    await emit(InvitationAccepted(
        tenant_id=str(invitation.tenant_id),
        user_id=str(user.id),
        email=user.email,
    ))

    access_token = create_access_token({"sub": str(user.id), "tenant_id": str(invitation.tenant_id)})
    _set_refresh_cookie(response, raw_refresh)

    logger.info("invitation_accepted", user_id=str(user.id), tenant_id=str(invitation.tenant_id))

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
            tenant_id=invitation.tenant_id,
            role=invitation.role.value,
            created_at=user.created_at,
        ),
    )
