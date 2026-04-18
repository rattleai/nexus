"""OAuth 2.1 Client Credentials flow for machine-to-machine authentication.

Management endpoints (create, list, revoke, rotate) are UI-only — they must
never be accessible via API keys or MCP to prevent privilege escalation.
The token exchange endpoint remains open for M2M auth by design.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireRole, RequireUI, get_current_tenant, get_db
from app.config import settings
from app.db.models import Tenant
from app.db.models.oauth_client import OAuthClient

logger = structlog.stdlib.get_logger()
router = APIRouter(prefix="/oauth")


# ── Schemas ──────────────────────────────────────────────


class OAuthClientCreate(BaseModel):
    name: str
    scopes: list[str] = []
    expires_at: datetime | None = None


class OAuthClientResponse(BaseModel):
    id: uuid.UUID
    client_id: str
    name: str
    scopes: list[str]
    active: bool
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class OAuthClientCreateResponse(OAuthClientResponse):
    client_secret: str  # Only returned on creation


class TokenRequest(BaseModel):
    grant_type: str
    client_id: str
    client_secret: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str


# ── Helpers ──────────────────────────────────────────────


def _hash_secret(secret: str) -> str:
    """Hash a client secret with HMAC-SHA256."""
    pepper = settings.SECRET_KEY.encode()
    return hmac.new(pepper, secret.encode(), hashlib.sha256).hexdigest()


def _generate_client_id() -> str:
    return f"cad_{secrets.token_urlsafe(24)}"


def _generate_client_secret() -> str:
    return secrets.token_urlsafe(48)


async def _audit_log(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    **extra: object,
) -> None:
    """Write an audit log entry for OAuth operations."""
    from app.db.models.operations import AuditLog

    entry = AuditLog(
        tenant_id=tenant_id,
        actor_type="oauth_client",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_=extra if extra else None,
    )
    db.add(entry)
    await db.commit()


# ── Endpoints ────────────────────────────────────────────


@router.post(
    "/clients",
    response_model=OAuthClientCreateResponse,
    status_code=201,
    dependencies=[Depends(RequireUI()), Depends(RequireRole("admin", "owner"))],
)
async def create_oauth_client(
    body: OAuthClientCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Register a new OAuth client for machine-to-machine authentication.

    Returns the client_id and client_secret. The secret is only shown once.
    """
    # Validate scopes
    invalid = set(body.scopes) - set(settings.VALID_SCOPES)
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid scopes: {', '.join(sorted(invalid))}")

    # Reject infrastructure scopes — they are UI-only and must not be
    # delegated to M2M clients.
    forbidden = set(body.scopes) & settings.INFRASTRUCTURE_SCOPES
    if forbidden:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot grant infrastructure scopes to OAuth clients: {', '.join(sorted(forbidden))}",
        )

    client_id = _generate_client_id()
    client_secret = _generate_client_secret()

    client = OAuthClient(
        tenant_id=tenant.id,
        client_id=client_id,
        client_secret_hash=_hash_secret(client_secret),
        name=body.name,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    db.add(client)
    await db.flush()
    await db.refresh(client)
    await db.commit()

    logger.info("oauth_client_created", client_id=client_id, tenant_id=str(tenant.id))
    await _audit_log(db, tenant.id, "create", "oauth_client", str(client.id), client_id=client_id)

    return OAuthClientCreateResponse(
        id=client.id,
        client_id=client_id,
        client_secret=client_secret,
        name=client.name,
        scopes=client.scopes or [],
        active=client.active,
        created_at=client.created_at,
    )


@router.get(
    "/clients",
    response_model=list[OAuthClientResponse],
    dependencies=[Depends(RequireUI()), Depends(RequireRole("admin", "owner"))],
)
async def list_oauth_clients(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all registered OAuth clients for the tenant."""
    result = await db.execute(
        select(OAuthClient).where(OAuthClient.tenant_id == tenant.id).order_by(OAuthClient.created_at.desc())
    )
    clients = result.scalars().all()

    return [
        OAuthClientResponse(
            id=c.id,
            client_id=c.client_id,
            name=c.name,
            scopes=c.scopes or [],
            active=c.active,
            created_at=c.created_at,
        )
        for c in clients
    ]


@router.delete(
    "/clients/{client_id}",
    status_code=204,
    dependencies=[Depends(RequireUI()), Depends(RequireRole("admin", "owner"))],
)
async def revoke_oauth_client(
    client_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an OAuth client."""
    result = await db.execute(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id,
            OAuthClient.tenant_id == tenant.id,
        )
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="OAuth client not found")

    client.active = False
    await db.commit()

    logger.info("oauth_client_revoked", client_id=client_id, tenant_id=str(tenant.id))
    await _audit_log(db, tenant.id, "revoke", "oauth_client", str(client.id), client_id=client_id)


@router.post(
    "/token",
    response_model=TokenResponse,
)
async def exchange_token(
    body: TokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange client credentials for an access token.

    Implements OAuth 2.1 Client Credentials grant.
    """
    if body.grant_type != "client_credentials":
        raise HTTPException(
            status_code=400,
            detail="Unsupported grant_type. Only 'client_credentials' is supported.",
        )

    # Look up client
    secret_hash = _hash_secret(body.client_secret)
    result = await db.execute(
        select(OAuthClient).where(
            OAuthClient.client_id == body.client_id,
            OAuthClient.client_secret_hash == secret_hash,
            OAuthClient.active.is_(True),
        )
    )
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=401, detail="Invalid client credentials")

    # Per-client rate limiting (prevents credential stuffing across distributed IPs)
    from app.api.rate_limit import _check_rate

    rl_key = f"rl:oauth_client:{client.client_id}"
    count = await _check_rate(rl_key, 10, 60)
    if count >= 10:
        raise HTTPException(
            status_code=429,
            detail="Too many token requests for this client",
            headers={"Retry-After": "60"},
        )

    # Check client expiry
    now = datetime.now(UTC)
    if client.expires_at and client.expires_at < now:
        raise HTTPException(status_code=401, detail="OAuth client has expired")

    # Update last_used_at
    client.last_used_at = now
    await db.commit()

    # Generate short-lived JWT
    from app.core.security import _get_effective_algorithm, _get_jwt_signing_key

    expires_in = 3600  # 1 hour
    payload = {
        "sub": str(client.id),
        "tenant_id": str(client.tenant_id),
        "client_id": client.client_id,
        "scopes": client.scopes or [],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "iss": "cadprice",
        "aud": "cadprice-api",
        "jti": uuid.uuid4().hex,
        "type": "client_credentials",
    }

    algorithm = _get_effective_algorithm()
    token = pyjwt.encode(payload, _get_jwt_signing_key(), algorithm=algorithm)

    scope_str = " ".join(client.scopes) if client.scopes else ""

    logger.info("oauth_token_issued", client_id=client.client_id, tenant_id=str(client.tenant_id))
    await _audit_log(db, client.tenant_id, "token_exchange", "oauth_client", str(client.id), client_id=client.client_id)

    return TokenResponse(
        access_token=token,
        token_type="Bearer",
        expires_in=expires_in,
        scope=scope_str,
    )


# ── Secret Rotation ────────────────────────────────────


class RotateSecretResponse(BaseModel):
    client_id: str
    client_secret: str


@router.post(
    "/clients/{client_id}/rotate",
    response_model=RotateSecretResponse,
    dependencies=[Depends(RequireUI()), Depends(RequireRole("admin", "owner"))],
)
async def rotate_client_secret(
    client_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Rotate the client secret for an OAuth client.

    Returns the new client_secret. The secret is only shown once.
    """
    result = await db.execute(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id,
            OAuthClient.tenant_id == tenant.id,
        )
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="OAuth client not found")

    new_secret = _generate_client_secret()
    client.client_secret_hash = _hash_secret(new_secret)
    await db.commit()

    logger.info("oauth_client_secret_rotated", client_id=client_id, tenant_id=str(tenant.id))
    await _audit_log(db, tenant.id, "rotate_secret", "oauth_client", str(client.id), client_id=client_id)

    return RotateSecretResponse(client_id=client_id, client_secret=new_secret)
