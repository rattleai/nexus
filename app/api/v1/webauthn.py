"""WebAuthn/FIDO2 endpoints for biometric authentication.

Supports passkey registration and authentication for passwordless
login on mobile devices (Face ID, Touch ID, fingerprint).

Uses py-webauthn for cryptographic verification and Redis for
ephemeral challenge storage with TTL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.api.deps import get_current_user_from_token, get_db
from app.api.rate_limit import RateLimiter
from app.config import settings
from app.core.redis import redis_pool
from app.db.models import User

_auth_begin_rate_limit = RateLimiter(max_requests=20, window=60, key_prefix="rl:webauthn-begin")

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/auth/webauthn", tags=["webauthn"])

CHALLENGE_TTL_SECONDS = 120  # 2 minutes for user to complete ceremony


def _challenge_key(purpose: str, identifier: str) -> str:
    return f"webauthn:{purpose}:{identifier}"


class RegistrationBeginResponse(BaseModel):
    publicKey: dict[str, Any]


class RegistrationCompleteRequest(BaseModel):
    id: str
    rawId: str
    response: dict[str, str]
    type: str = "public-key"
    authenticatorAttachment: str | None = None
    clientExtensionResults: dict[str, Any] = Field(default_factory=dict)
    device_name: str = "Unknown device"


class AuthenticationBeginResponse(BaseModel):
    publicKey: dict[str, Any]


class AuthenticationCompleteRequest(BaseModel):
    id: str
    rawId: str
    response: dict[str, Any]
    type: str = "public-key"
    authenticatorAttachment: str | None = None
    clientExtensionResults: dict[str, Any] = Field(default_factory=dict)


@router.post("/register/begin", response_model=RegistrationBeginResponse)
async def registration_begin(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> RegistrationBeginResponse:
    """Begin WebAuthn credential registration.

    Returns PublicKeyCredentialCreationOptions for the browser's
    navigator.credentials.create() call. Challenge is stored in Redis with TTL.
    """
    from app.db.models.mobile import WebAuthnCredential

    result = await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id))
    existing = result.scalars().all()

    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in existing if c.credential_id
    ]

    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(user.id).encode(),
        user_name=user.email,
        user_display_name=user.display_name or user.email,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude_credentials,
        timeout=60000,
    )

    # Store challenge in Redis with TTL
    challenge_b64 = bytes_to_base64url(options.challenge)
    await redis_pool.setex(
        _challenge_key("register", str(user.id)),
        CHALLENGE_TTL_SECONDS,
        challenge_b64,
    )

    options_dict = {
        "challenge": challenge_b64,
        "rp": {"name": options.rp.name, "id": options.rp.id},
        "user": {
            "id": bytes_to_base64url(options.user.id),
            "name": options.user.name,
            "displayName": options.user.display_name,
        },
        "pubKeyCredParams": [{"type": "public-key", "alg": p.alg} for p in options.pub_key_cred_params],
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",
            "userVerification": "preferred",
            "residentKey": "preferred",
            "requireResidentKey": False,
        },
        "timeout": options.timeout,
        "excludeCredentials": [
            {"type": "public-key", "id": bytes_to_base64url(c.id)} for c in (options.exclude_credentials or [])
        ],
        "attestation": "none",
    }

    return RegistrationBeginResponse(publicKey=options_dict)


@router.post("/register/complete")
async def registration_complete(
    body: RegistrationCompleteRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Complete WebAuthn credential registration.

    Verifies the attestation response using py-webauthn and stores the credential.
    """
    from app.db.models.mobile import WebAuthnCredential

    # Retrieve and consume the challenge from Redis
    challenge_key = _challenge_key("register", str(user.id))
    stored_challenge = await redis_pool.getdel(challenge_key)
    if not stored_challenge:
        raise HTTPException(status_code=400, detail="Registration challenge expired or not found")

    try:
        verification = verify_registration_response(
            credential={
                "id": body.id,
                "rawId": body.rawId,
                "response": body.response,
                "type": body.type,
                "authenticatorAttachment": body.authenticatorAttachment,
                "clientExtensionResults": body.clientExtensionResults,
            },
            expected_challenge=base64url_to_bytes(stored_challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
        )
    except Exception as e:
        logger.warning("webauthn_registration_failed", user_id=str(user.id), error=str(e))
        raise HTTPException(status_code=400, detail="WebAuthn registration verification failed") from e

    credential = WebAuthnCredential(
        user_id=user.id,
        credential_id=bytes_to_base64url(verification.credential_id),
        public_key=bytes_to_base64url(verification.credential_public_key),
        sign_count=verification.sign_count,
        device_name=body.device_name,
    )
    db.add(credential)

    # Auto-enable MFA on first WebAuthn credential registration
    if not user.mfa_enabled:
        user.mfa_enabled = True

    await db.flush()
    await db.refresh(credential)
    await db.commit()

    logger.info("webauthn_registered", user_id=str(user.id), device=body.device_name, mfa_enabled=True)
    return {"credential_id": str(credential.id)}


@router.post(
    "/authenticate/begin", response_model=AuthenticationBeginResponse, dependencies=[Depends(_auth_begin_rate_limit)]
)
async def authentication_begin() -> AuthenticationBeginResponse:
    """Begin WebAuthn authentication.

    Returns PublicKeyCredentialRequestOptions for the browser's
    navigator.credentials.get() call.
    """
    session_id = str(uuid.uuid4())

    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        user_verification=UserVerificationRequirement.PREFERRED,
        timeout=60000,
    )

    challenge_b64 = bytes_to_base64url(options.challenge)
    await redis_pool.setex(
        _challenge_key("auth", session_id),
        CHALLENGE_TTL_SECONDS,
        challenge_b64,
    )

    options_dict = {
        "challenge": challenge_b64,
        "rpId": settings.WEBAUTHN_RP_ID,
        "timeout": options.timeout,
        "userVerification": "preferred",
        "allowCredentials": [],
        "sessionId": session_id,
    }

    return AuthenticationBeginResponse(publicKey=options_dict)


@router.post("/authenticate/complete")
async def authentication_complete(
    body: AuthenticationCompleteRequest,
    session_id: str = Query(..., description="Session ID from authentication/begin response"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Complete WebAuthn authentication.

    Verifies the assertion signature and returns a JWT access token.
    """
    from app.db.models.mobile import WebAuthnCredential

    challenge_key = _challenge_key("auth", session_id)
    stored_challenge = await redis_pool.getdel(challenge_key)
    if not stored_challenge:
        raise HTTPException(status_code=400, detail="Authentication challenge expired or not found")

    result = await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.credential_id == body.id))
    credential = result.scalar_one_or_none()
    if not credential:
        raise HTTPException(status_code=401, detail="Unknown credential")

    try:
        verification = verify_authentication_response(
            credential={
                "id": body.id,
                "rawId": body.rawId,
                "response": body.response,
                "type": body.type,
                "authenticatorAttachment": body.authenticatorAttachment,
                "clientExtensionResults": body.clientExtensionResults,
            },
            expected_challenge=base64url_to_bytes(stored_challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=base64url_to_bytes(credential.public_key),
            credential_current_sign_count=credential.sign_count,
        )
    except Exception as e:
        logger.warning("webauthn_auth_failed", credential_id=body.id, error=str(e))
        raise HTTPException(status_code=401, detail="WebAuthn authentication verification failed") from e

    credential.sign_count = verification.new_sign_count
    credential.last_used_at = datetime.now(UTC)

    from app.db.models import User as UserModel

    user_result = await db.execute(select(UserModel).where(UserModel.id == credential.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    await db.commit()

    from app.core.security import create_access_token

    access_token = create_access_token(
        {
            "sub": str(user.id),
            "tenant_id": str(user.tenant_id),
            "amr": ["hwk", "mfa"],
        }
    )

    logger.info("webauthn_authenticated", user_id=str(user.id))
    return {"access_token": access_token}


# ── MFA Verification ────────────────────────────────────────────────────


class MFAVerifyRequest(BaseModel):
    """Request body for MFA verification after password login."""

    mfa_token: str = Field(..., description="The MFA-pending token from password login")
    id: str
    rawId: str
    response: dict[str, Any]
    type: str = "public-key"
    authenticatorAttachment: str | None = None
    clientExtensionResults: dict[str, Any] = Field(default_factory=dict)


@router.post("/mfa/verify")
async def verify_mfa(
    body: MFAVerifyRequest,
    session_id: str = Query(..., description="Session ID from authentication/begin"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Complete MFA verification after password login.

    Accepts an MFA-pending token + WebAuthn assertion, and issues a full
    access token with amr=["pwd", "mfa"].
    """
    # Validate the MFA-pending token
    import jwt as pyjwt

    from app.core.security import _get_effective_algorithm, _get_jwt_verification_key
    from app.db.models.mobile import WebAuthnCredential

    try:
        algorithm = _get_effective_algorithm()
        payload = pyjwt.decode(
            body.mfa_token,
            _get_jwt_verification_key(),
            algorithms=[algorithm],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="MFA token has expired") from None
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid MFA token") from None

    if payload.get("type") != "mfa_pending":
        raise HTTPException(status_code=401, detail="Not an MFA-pending token")

    user_id = payload.get("sub")
    tenant_id = payload.get("tenant_id")

    # Retrieve and consume the WebAuthn challenge
    challenge_key = _challenge_key("auth", session_id)
    stored_challenge = await redis_pool.getdel(challenge_key)
    if not stored_challenge:
        raise HTTPException(status_code=400, detail="Authentication challenge expired or not found")

    # Find the credential
    result = await db.execute(select(WebAuthnCredential).where(WebAuthnCredential.credential_id == body.id))
    credential = result.scalar_one_or_none()
    if not credential:
        raise HTTPException(status_code=401, detail="Unknown credential")

    # Verify the credential belongs to the MFA-pending user
    if str(credential.user_id) != user_id:
        raise HTTPException(status_code=401, detail="Credential does not belong to this user")

    try:
        verification = verify_authentication_response(
            credential={
                "id": body.id,
                "rawId": body.rawId,
                "response": body.response,
                "type": body.type,
                "authenticatorAttachment": body.authenticatorAttachment,
                "clientExtensionResults": body.clientExtensionResults,
            },
            expected_challenge=base64url_to_bytes(stored_challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=base64url_to_bytes(credential.public_key),
            credential_current_sign_count=credential.sign_count,
        )
    except Exception as e:
        logger.warning("mfa_verification_failed", user_id=user_id, error=str(e))
        raise HTTPException(status_code=401, detail="MFA verification failed") from e

    credential.sign_count = verification.new_sign_count
    credential.last_used_at = datetime.now(UTC)
    await db.commit()

    # Issue full access token with MFA AMR
    from app.core.security import create_access_token

    # Combine AMR from MFA-pending token with "mfa"
    original_amr = payload.get("amr", ["pwd"])
    full_amr = list({*original_amr, "mfa"})

    access_token = create_access_token(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "amr": full_amr,
        }
    )

    logger.info("mfa_verified", user_id=user_id)
    return {"access_token": access_token, "amr": full_amr}
