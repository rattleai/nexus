"""Connector catalog, OAuth flow, and per-tenant app credential endpoints.

Provides:
    - Connector definition browsing (marketplace)
    - OAuth flow initiation and callback (per-user identity threaded through)
    - Per-tenant OAuth app credential registration (P0.1)
    - RFC 7591 Dynamic Client Registration (P1.2)
    - Custom MCP server registration with trust-level enforcement (P1.3)
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    RequireScopes,
    _resolve_user_from_jwt,
    get_current_tenant,
    get_db,
)
from app.api.rate_limit import ApiKeyRateLimiter
from app.api.schemas_connectors import (
    AppCredentialsRead,
    AppCredentialsRegisterRequest,
    ConnectorDefinitionList,
    ConnectorDefinitionRead,
    DynamicClientRegisterRequest,
    DynamicClientRegisterResponse,
    OAuthStartResponse,
    RegisterMCPServerRequest,
)
from app.config import settings
from app.core.audit import AuditAction, emit_audit_event
from app.db.models import Tenant, User


async def _optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the JWT user if present, else None (API-key callers)."""
    try:
        return await _resolve_user_from_jwt(request, db)
    except HTTPException:
        return None

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/connectors", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()


# ── Catalog Endpoints ────────────────────────────────────


@router.get(
    "",
    response_model=ConnectorDefinitionList,
    dependencies=[Depends(RequireScopes("connections:read"))],
)
async def list_connectors(
    category: str | None = Query(default=None, max_length=50),
    connector_type: str | None = Query(default=None, max_length=20),
    search: str | None = Query(default=None, max_length=255),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List available connector definitions (the marketplace catalog)."""
    from app.connectors.registry import connector_registry

    connectors = await connector_registry.list_connectors(
        db,
        category=category,
        connector_type=connector_type,
        search=search,
    )
    return ConnectorDefinitionList(items=connectors, total=len(connectors))


@router.get(
    "/{slug}",
    response_model=ConnectorDefinitionRead,
    dependencies=[Depends(RequireScopes("connections:read"))],
)
async def get_connector(
    slug: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get a single connector definition by slug."""
    from app.connectors.registry import connector_registry

    connector = await connector_registry.get_connector(db, slug)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector '{slug}' not found")
    return connector


# ── Per-Tenant OAuth App Credentials (P0.1) ─────────────


@router.get(
    "/{slug}/app-credentials",
    response_model=AppCredentialsRead,
    dependencies=[Depends(RequireScopes("connections:admin"))],
)
async def get_app_credentials(
    slug: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Check whether this tenant has registered an OAuth app for the connector."""
    from app.connectors.app_credentials import app_credential_manager

    creds = await app_credential_manager.get(
        tenant_id=tenant.id, connector_slug=slug, db=db,
    )
    if creds is None:
        return AppCredentialsRead(
            connector_slug=slug,
            is_registered=False,
        )

    preview = (creds.client_id or "")[-4:] if creds.client_id else None
    return AppCredentialsRead(
        connector_slug=slug,
        is_registered=True,
        client_id_preview=f"…{preview}" if preview else None,
        redirect_uri_override=creds.redirect_uri_override,
        has_webhook_secret=bool(creds.webhook_secret),
    )


@router.post(
    "/{slug}/app-credentials",
    response_model=AppCredentialsRead,
    status_code=201,
    dependencies=[Depends(RequireScopes("connections:admin"))],
)
async def register_app_credentials(
    slug: str,
    body: AppCredentialsRegisterRequest,
    tenant: Tenant = Depends(get_current_tenant),
    user: User | None = Depends(_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Register or rotate OAuth app credentials for a connector in this tenant.

    Secrets are encrypted at rest and isolated by RLS. Calling this endpoint
    twice performs a rotation — the most recent client_id/client_secret wins.
    """
    from app.connectors.app_credentials import app_credential_manager
    from app.connectors.registry import connector_registry

    connector = await connector_registry.get_connector(db, slug)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector '{slug}' not found")

    row = await app_credential_manager.register(
        tenant_id=tenant.id,
        connector_slug=slug,
        client_id=body.client_id,
        client_secret=body.client_secret,
        webhook_secret=body.webhook_secret,
        redirect_uri_override=body.redirect_uri_override,
        extra_config=body.extra_config,
        created_by_user_id=user.id if user else None,
        db=db,
    )

    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="connector_app_credentials",
        resource_id=str(row.id),
        tenant_id=tenant.id,
        changes={"connector_slug": slug},
    )
    await db.commit()

    preview = (body.client_id or "")[-4:]
    return AppCredentialsRead(
        connector_slug=slug,
        is_registered=True,
        client_id_preview=f"…{preview}",
        redirect_uri_override=body.redirect_uri_override,
        has_webhook_secret=bool(body.webhook_secret),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete(
    "/{slug}/app-credentials",
    status_code=204,
    dependencies=[Depends(RequireScopes("connections:admin"))],
)
async def delete_app_credentials(
    slug: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete the OAuth app credentials for this tenant + connector."""
    from app.connectors.app_credentials import app_credential_manager

    removed = await app_credential_manager.delete(
        tenant_id=tenant.id, connector_slug=slug, db=db,
    )
    if not removed:
        raise HTTPException(status_code=404, detail="No app credentials registered")

    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="connector_app_credentials",
        resource_id=slug,
        tenant_id=tenant.id,
    )
    await db.commit()


# ── Dynamic Client Registration (P1.2) ──────────────────


@router.post(
    "/{slug}/register-client",
    response_model=DynamicClientRegisterResponse,
    dependencies=[Depends(RequireScopes("connections:admin"))],
)
async def register_oauth_client(
    slug: str,
    body: DynamicClientRegisterRequest,
    tenant: Tenant = Depends(get_current_tenant),
    user: User | None = Depends(_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Run RFC 7591 Dynamic Client Registration for a connector.

    Walks RFC 9728 protected-resource-metadata → RFC 8414 authorization-server-metadata
    → RFC 7591 client registration. On success, stores the returned client_id and
    client_secret as per-tenant app credentials.
    """
    from app.connectors.app_credentials import app_credential_manager
    from app.connectors.oauth_discovery import (
        DiscoveryError,
        discover_authorization,
        dynamic_register_client,
    )
    from app.connectors.registry import connector_registry

    connector = await connector_registry.get_connector(db, slug)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector '{slug}' not found")

    try:
        metadata = await discover_authorization(connector, db=db)
    except DiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not metadata.registration_endpoint:
        raise HTTPException(
            status_code=400,
            detail=(
                "This provider does not advertise a Dynamic Client Registration "
                "endpoint. Register the OAuth app manually via POST /app-credentials."
            ),
        )

    try:
        client_id, client_secret = await dynamic_register_client(
            metadata=metadata,
            client_name=body.client_name,
            redirect_uris=body.redirect_uris,
        )
    except DiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await app_credential_manager.register(
        tenant_id=tenant.id,
        connector_slug=slug,
        client_id=client_id,
        client_secret=client_secret,
        created_by_user_id=user.id if user else None,
        db=db,
    )
    await db.commit()

    return DynamicClientRegisterResponse(
        client_id=client_id,
        registration_endpoint=metadata.registration_endpoint,
        authorize_url=metadata.authorize_url,
        token_url=metadata.token_url,
        scopes_supported=metadata.scopes_supported,
    )


# ── MCP Server Registration ─────────────────────────────


@router.post(
    "/register-mcp",
    response_model=ConnectorDefinitionRead,
    status_code=201,
    dependencies=[Depends(RequireScopes("connections:admin"))],
)
async def register_mcp_server(
    body: RegisterMCPServerRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Register a custom remote MCP server as a connector definition.

    In production, the MCP server must pass signed-registry verification
    (P1.3) before it can be registered. Non-verified servers are rejected
    unless ``CONNECTOR_REGISTRY_ALLOW_UNTRUSTED`` is enabled.
    """
    from app.connectors.registry import connector_registry
    from app.connectors.registry_verification import (
        RegistryVerificationError,
        verify_mcp_server,
    )

    try:
        trust = await verify_mcp_server(body.url)
    except RegistryVerificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        connector = await connector_registry.register_mcp_server(
            db,
            url=body.url,
            name=body.name,
            description=body.description,
            tenant_id=tenant.id,
            trust_level=trust,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="connector_definition",
        resource_id=str(connector.id),
        tenant_id=tenant.id,
        changes={"url": body.url, "name": body.name, "trust_level": trust.value},
    )
    await db.commit()
    await db.refresh(connector)
    return connector


# ── OAuth Flow ───────────────────────────────────────────


def _default_redirect_uri() -> str:
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    if not origins:
        return "http://localhost:3000/auth/callback/connector"
    return f"{origins[0]}/auth/callback/connector"


@router.post(
    "/{slug}/auth/start",
    response_model=OAuthStartResponse,
    dependencies=[Depends(RequireScopes("connections:write"))],
)
async def start_oauth_flow(
    slug: str,
    tenant: Tenant = Depends(get_current_tenant),
    user: User | None = Depends(_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Start the OAuth authorization flow for a connector.

    Threads the invoking user's ID into the OAuth state so the resulting
    connection is scoped to ``connected_by_user_id``.
    """
    from app.connectors.oauth_flow import OAuthFlowError, oauth_flow
    from app.connectors.registry import connector_registry

    connector = await connector_registry.get_connector(db, slug)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector '{slug}' not found")

    if connector.auth_type != "oauth2":
        raise HTTPException(
            status_code=400,
            detail=f"Connector '{slug}' does not use OAuth authentication",
        )

    try:
        result = await oauth_flow.start(
            connector_def=connector,
            tenant_id=tenant.id,
            redirect_uri=_default_redirect_uri(),
            user_id=user.id if user else None,
            db=db,
        )
    except OAuthFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    return OAuthStartResponse(**result)


@router.get(
    "/{slug}/auth/callback",
    dependencies=[Depends(RequireScopes("connections:write"))],
)
async def oauth_callback(
    slug: str,
    code: str = Query(...),
    state: str = Query(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback: exchange code for tokens, create connection."""
    from app.api.schemas_connectors import ConnectionRead
    from app.connectors.oauth_flow import OAuthFlowError, oauth_flow
    from app.connectors.registry import connector_registry

    connector = await connector_registry.get_connector(db, slug)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector '{slug}' not found")

    try:
        connection = await oauth_flow.callback(
            connector_def=connector,
            code=code,
            state=state,
            tenant_id=tenant.id,
            redirect_uri=_default_redirect_uri(),
            db=db,
        )
    except OAuthFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="tenant_connection",
        resource_id=str(connection.id),
        tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(connection)

    return ConnectionRead(
        id=connection.id,
        tenant_id=connection.tenant_id,
        connector_definition_id=connection.connector_definition_id,
        display_name=connection.display_name,
        account_identifier=connection.account_identifier,
        status=connection.status,
        status_message=connection.status_message,
        connector_slug=connector.slug,
        connector_name=connector.name,
        connector_icon=connector.icon,
        connector_type=connector.connector_type,
        last_used_at=connection.last_used_at,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


# ── Webhook Endpoint ─────────────────────────────────────
# Webhook receiver is mounted on this router so it lives at
# POST /api/v1/connectors/{slug}/webhook/{tenant_id} (tenant-scoped per P0.1/P0.9).

from app.connectors.webhook_receiver import router as _webhook_router

router.include_router(_webhook_router)
