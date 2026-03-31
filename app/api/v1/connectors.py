"""Connector catalog and OAuth flow endpoints.

Provides:
    - Connector definition browsing (marketplace)
    - OAuth flow initiation and callback
    - Custom MCP server registration
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.api.schemas_connectors import (
    ConnectorDefinitionList,
    ConnectorDefinitionRead,
    OAuthStartResponse,
    RegisterMCPServerRequest,
)
from app.config import settings
from app.core.audit import AuditAction, emit_audit_event
from app.db.models import Tenant

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
    """Register a custom remote MCP server as a connector definition."""
    from app.connectors.registry import connector_registry

    try:
        connector = await connector_registry.register_mcp_server(
            db,
            url=body.url,
            name=body.name,
            description=body.description,
            tenant_id=tenant.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="connector_definition",
        resource_id=str(connector.id),
        tenant_id=tenant.id,
        changes={"url": body.url, "name": body.name},
    )
    await db.commit()
    await db.refresh(connector)
    return connector


# ── OAuth Flow ───────────────────────────────────────────


@router.post(
    "/{slug}/auth/start",
    response_model=OAuthStartResponse,
    dependencies=[Depends(RequireScopes("connections:write"))],
)
async def start_oauth_flow(
    slug: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Start the OAuth authorization flow for a connector.

    Returns the authorization URL the client should redirect to.
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

    # Use the server-configured redirect URI
    redirect_uri = (connector.auth_config or {}).get(
        "redirect_uri", f"{settings.CORS_ORIGINS.split(',')[0]}/auth/callback/connector",
    )

    try:
        result = await oauth_flow.start(
            connector_def=connector,
            tenant_id=tenant.id,
            redirect_uri=redirect_uri,
        )
    except OAuthFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    from app.connectors.oauth_flow import OAuthFlowError, oauth_flow
    from app.connectors.registry import connector_registry

    connector = await connector_registry.get_connector(db, slug)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector '{slug}' not found")

    redirect_uri = (connector.auth_config or {}).get(
        "redirect_uri", f"{settings.CORS_ORIGINS.split(',')[0]}/auth/callback/connector",
    )

    try:
        connection = await oauth_flow.callback(
            connector_def=connector,
            code=code,
            state=state,
            tenant_id=tenant.id,
            redirect_uri=redirect_uri,
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

    from app.api.schemas_connectors import ConnectionRead

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
