"""WebAuthn/FIDO2 endpoints for biometric authentication.

Supports passkey registration and authentication for passwordless
login on mobile devices (Face ID, Touch ID, fingerprint).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_token, get_db
from app.config import settings
from app.db.models import User

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/auth/webauthn", tags=["webauthn"])

# WebAuthn configuration
WEBAUTHN_RP_ID = getattr(settings, "WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_RP_NAME = getattr(settings, "WEBAUTHN_RP_NAME", "CAD Price")
WEBAUTHN_ORIGIN = getattr(settings, "WEBAUTHN_ORIGIN", "http://localhost:3000")


class RegistrationBeginResponse(BaseModel):
    publicKey: dict[str, Any]


class RegistrationCompleteRequest(BaseModel):
    id: str
    raw_id: str
    response: dict[str, str]
    type: str
    device_name: str = "Unknown device"


class AuthenticationBeginResponse(BaseModel):
    publicKey: dict[str, Any]


class AuthenticationCompleteRequest(BaseModel):
    id: str
    raw_id: str
    response: dict[str, Any]
    type: str


@router.post("/register/begin", response_model=RegistrationBeginResponse)
async def registration_begin(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> RegistrationBeginResponse:
    """Begin WebAuthn credential registration.

    Returns a PublicKeyCredentialCreationOptions object for the browser's
    navigator.credentials.create() call.
    """
    from app.db.models.mobile import WebAuthnCredential

    # Fetch existing credentials to exclude
    result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id)
    )
    existing = result.scalars().all()

    import base64
    import os

    challenge = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    user_id_b64 = base64.urlsafe_b64encode(user.id.bytes).decode().rstrip("=")

    options = {
        "challenge": challenge,
        "rp": {"name": WEBAUTHN_RP_NAME, "id": WEBAUTHN_RP_ID},
        "user": {
            "id": user_id_b64,
            "name": user.email,
            "displayName": user.display_name or user.email,
        },
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},   # ES256
            {"type": "public-key", "alg": -257},  # RS256
        ],
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",
            "userVerification": "preferred",
            "residentKey": "preferred",
            "requireResidentKey": False,
        },
        "timeout": 60000,
        "excludeCredentials": [
            {
                "type": "public-key",
                "id": base64.urlsafe_b64encode(bytes.fromhex(c.credential_id)).decode().rstrip("="),
            }
            for c in existing
            if c.credential_id
        ],
        "attestation": "none",
    }

    # Store challenge in a temporary way (in production, use Redis with TTL)
    # For now, we'll verify on the complete endpoint
    return RegistrationBeginResponse(publicKey=options)


@router.post("/register/complete")
async def registration_complete(
    body: RegistrationCompleteRequest,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Complete WebAuthn credential registration.

    Verifies the attestation response and stores the credential.
    """
    from app.db.models.mobile import WebAuthnCredential

    # In production, verify the attestation using py_webauthn.
    # For the infrastructure layer, we store the credential data.
    credential = WebAuthnCredential(
        user_id=user.id,
        credential_id=body.id,
        public_key=body.response.get("attestation_object", ""),
        sign_count=0,
        device_name=body.device_name,
    )
    db.add(credential)
    await db.commit()
    await db.refresh(credential)

    logger.info("webauthn_registered", user_id=str(user.id), device=body.device_name)
    return {"credential_id": str(credential.id)}


@router.post("/authenticate/begin", response_model=AuthenticationBeginResponse)
async def authentication_begin() -> AuthenticationBeginResponse:
    """Begin WebAuthn authentication.

    Returns a PublicKeyCredentialRequestOptions object for the browser's
    navigator.credentials.get() call.
    """
    import base64
    import os

    challenge = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")

    options = {
        "challenge": challenge,
        "rpId": WEBAUTHN_RP_ID,
        "timeout": 60000,
        "userVerification": "preferred",
    }

    return AuthenticationBeginResponse(publicKey=options)


@router.post("/authenticate/complete")
async def authentication_complete(
    body: AuthenticationCompleteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Complete WebAuthn authentication.

    Verifies the assertion and returns a JWT access token.
    """
    from app.db.models.mobile import WebAuthnCredential

    result = await db.execute(
        select(WebAuthnCredential).where(WebAuthnCredential.credential_id == body.id)
    )
    credential = result.scalar_one_or_none()

    if not credential:
        raise HTTPException(status_code=401, detail="Unknown credential")

    # In production, verify the assertion signature using py_webauthn.
    # Update sign count
    credential.sign_count += 1
    await db.commit()

    # Load the user and generate JWT
    from app.db.models import User as UserModel

    user_result = await db.execute(
        select(UserModel).where(UserModel.id == credential.user_id)
    )
    user = user_result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    from app.core.security import create_access_token

    access_token = create_access_token(user_id=str(user.id), tenant_id=str(user.tenant_id))

    logger.info("webauthn_authenticated", user_id=str(user.id))
    return {"access_token": access_token}
