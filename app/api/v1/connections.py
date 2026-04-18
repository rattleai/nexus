"""Tenant connection management endpoints.

Provides:
    - CRUD for connections (list, create, update, delete)
    - Connection health testing
    - Tool listing and discovery refresh
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.api.schemas_connectors import (
    ConnectionCreateRequest,
    ConnectionDetailRead,
    ConnectionList,
    ConnectionRead,
    ConnectionTestResult,
    ConnectionToolRead,
    ConnectionUpdateRequest,
)
from app.connectors.models import (
    AuthType,
    ConnectionStatus,
    ConnectorDefinition,
    TenantConnection,
    TenantCredential,
)
from app.core.audit import AuditAction, emit_audit_event
from app.core.tenant import tenant_query
from app.db.models import Tenant

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/connections", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()


# ── Helpers ──────────────────────────────────────────────


async def _get_connection(
    connection_id: uuid.UUID,
    tenant: Tenant,
    db: AsyncSession,
) -> TenantConnection:
    """Fetch a connection scoped to the tenant, or raise 404."""
    result = await db.execute(
        tenant_query(select(TenantConnection), tenant)
        .where(
            TenantConnection.id == connection_id,
            TenantConnection.deleted_at.is_(None),
        )
        .options(joinedload(TenantConnection.connector_definition))
    )
    conn = result.unique().scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


def _to_read(conn: TenantConnection) -> ConnectionRead:
    """Convert a TenantConnection to a ConnectionRead schema."""
    cd = conn.connector_definition
    tools_cache = conn.mcp_tools_cache or []
    resources_cache = conn.mcp_resources_cache or []

    return ConnectionRead(
        id=conn.id,
        tenant_id=conn.tenant_id,
        connector_definition_id=conn.connector_definition_id,
        display_name=conn.display_name,
        account_identifier=conn.account_identifier,
        status=conn.status,
        status_message=conn.status_message,
        connector_slug=cd.slug if cd else None,
        connector_name=cd.name if cd else None,
        connector_icon=cd.icon if cd else None,
        connector_type=cd.connector_type if cd else None,
        tools_count=len(tools_cache) if isinstance(tools_cache, list) else 0,
        resources_count=len(resources_cache) if isinstance(resources_cache, list) else 0,
        last_used_at=conn.last_used_at,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


# ── Endpoints ────────────────────────────────────────────


@router.get(
    "",
    response_model=ConnectionList,
    dependencies=[Depends(RequireScopes("connections:read"))],
)
async def list_connections(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all active connections for the current tenant."""
    result = await db.execute(
        tenant_query(select(TenantConnection), tenant)
        .where(TenantConnection.deleted_at.is_(None))
        .options(joinedload(TenantConnection.connector_definition))
        .order_by(TenantConnection.created_at.desc())
    )
    connections = result.unique().scalars().all()
    return ConnectionList(
        items=[_to_read(c) for c in connections],
        total=len(connections),
    )


@router.post(
    "",
    response_model=ConnectionRead,
    status_code=201,
    dependencies=[Depends(RequireScopes("connections:write"))],
)
async def create_connection(
    body: ConnectionCreateRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new connection for API key, bearer token, or no-auth connectors.

    For OAuth connectors, use the ``/connectors/{slug}/auth/start`` endpoint instead.
    """
    from app.connectors.credentials import credential_manager
    from app.connectors.registry import connector_registry

    connector = await connector_registry.get_connector(db, body.connector_slug)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector '{body.connector_slug}' not found")

    if connector.auth_type == AuthType.OAUTH2:
        raise HTTPException(
            status_code=400,
            detail="OAuth connectors must be connected via the OAuth flow endpoint",
        )

    connection = TenantConnection(
        tenant_id=tenant.id,
        connector_definition_id=connector.id,
        display_name=body.display_name,
        status=ConnectionStatus.ACTIVE,
    )
    db.add(connection)
    await db.flush()

    # Store credential if provided
    if body.api_key and connector.auth_type == AuthType.API_KEY:
        await credential_manager.store_api_key(
            connection=connection,
            api_key=body.api_key,
            auth_metadata=None,
            db=db,
        )
    elif body.bearer_token and connector.auth_type == AuthType.BEARER_TOKEN:
        await credential_manager.store_bearer_token(
            connection=connection,
            token=body.bearer_token,
            auth_metadata=None,
            db=db,
        )

    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="tenant_connection",
        resource_id=str(connection.id),
        tenant_id=tenant.id,
    )
    await db.commit()

    # Reload with relationship
    result = await db.execute(
        select(TenantConnection)
        .where(TenantConnection.id == connection.id)
        .options(joinedload(TenantConnection.connector_definition))
    )
    connection = result.unique().scalar_one()

    return _to_read(connection)


@router.get(
    "/{connection_id}",
    response_model=ConnectionDetailRead,
    dependencies=[Depends(RequireScopes("connections:read"))],
)
async def get_connection(
    connection_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed connection information including health and tools."""
    conn = await _get_connection(connection_id, tenant, db)
    cd = conn.connector_definition
    tools_cache = conn.mcp_tools_cache or []
    resources_cache = conn.mcp_resources_cache or []

    return ConnectionDetailRead(
        id=conn.id,
        tenant_id=conn.tenant_id,
        connector_definition_id=conn.connector_definition_id,
        display_name=conn.display_name,
        account_identifier=conn.account_identifier,
        status=conn.status,
        status_message=conn.status_message,
        connector_slug=cd.slug if cd else None,
        connector_name=cd.name if cd else None,
        connector_icon=cd.icon if cd else None,
        connector_type=cd.connector_type if cd else None,
        tools_count=len(tools_cache) if isinstance(tools_cache, list) else 0,
        resources_count=len(resources_cache) if isinstance(resources_cache, list) else 0,
        health_status=conn.health_status,
        health_checked_at=conn.health_checked_at,
        cache_refreshed_at=conn.cache_refreshed_at,
        config_overrides=conn.config_overrides,
        last_used_at=conn.last_used_at,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


@router.patch(
    "/{connection_id}",
    response_model=ConnectionRead,
    dependencies=[Depends(RequireScopes("connections:write"))],
)
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdateRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update a connection's display name or configuration."""
    conn = await _get_connection(connection_id, tenant, db)

    if body.display_name is not None:
        conn.display_name = body.display_name
    if body.config_overrides is not None:
        conn.config_overrides = body.config_overrides

    await emit_audit_event(
        db,
        action=AuditAction.UPDATE,
        resource_type="tenant_connection",
        resource_id=str(conn.id),
        tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(conn)

    return _to_read(conn)


@router.delete(
    "/{connection_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("connections:write"))],
)
async def delete_connection(
    connection_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect: soft-delete the connection and revoke credentials."""
    conn = await _get_connection(connection_id, tenant, db)
    cd = conn.connector_definition

    # Revoke credentials if present
    if conn.credential:
        from app.connectors.credentials import credential_manager

        await credential_manager.revoke(conn.credential, cd, db)

    conn.deleted_at = datetime.now(UTC)
    conn.status = ConnectionStatus.DISCONNECTED

    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="tenant_connection",
        resource_id=str(conn.id),
        tenant_id=tenant.id,
    )
    await db.commit()

    logger.info(
        "connection_deleted",
        connection_id=str(connection_id),
        tenant_id=str(tenant.id),
    )


@router.post(
    "/{connection_id}/test",
    response_model=ConnectionTestResult,
    dependencies=[Depends(RequireScopes("connections:read"))],
)
async def test_connection(
    connection_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Test a connection's health (credential validity, server reachability)."""
    import time

    conn = await _get_connection(connection_id, tenant, db)
    cd = conn.connector_definition
    start = time.monotonic()

    try:
        # For OAuth/API key connectors: verify token is still valid
        if cd.auth_type != AuthType.NONE:
            from app.connectors.credentials import CredentialError, credential_manager

            try:
                await credential_manager.get_valid_token(conn, cd, db)
            except CredentialError as exc:
                latency = int((time.monotonic() - start) * 1000)
                conn.health_status = {"status": "error", "message": str(exc)}
                conn.health_checked_at = datetime.now(UTC)
                await db.commit()
                return ConnectionTestResult(
                    status="error", message=str(exc), latency_ms=latency,
                )

        latency = int((time.monotonic() - start) * 1000)
        conn.health_status = {"status": "ok"}
        conn.health_checked_at = datetime.now(UTC)
        await db.commit()

        return ConnectionTestResult(
            status="ok",
            message="Connection is healthy",
            latency_ms=latency,
        )

    except Exception as exc:
        latency = int((time.monotonic() - start) * 1000)
        return ConnectionTestResult(
            status="error",
            message=f"Health check failed: {str(exc)[:200]}",
            latency_ms=latency,
        )


@router.get(
    "/{connection_id}/tools",
    response_model=list[ConnectionToolRead],
    dependencies=[Depends(RequireScopes("connections:read"))],
)
async def list_connection_tools(
    connection_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List tools available via this connection."""
    conn = await _get_connection(connection_id, tenant, db)
    cd = conn.connector_definition

    # MCP connectors: return cached tools
    if cd.connector_type == "mcp_server":
        tools = conn.mcp_tools_cache or []
        return [
            ConnectionToolRead(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema") or t.get("input_schema"),
            )
            for t in tools
        ]

    # Non-MCP connectors: return tool_definitions from connector def
    tool_defs = cd.tool_definitions or []
    return [
        ConnectionToolRead(
            name=t.get("name", ""),
            description=t.get("description", ""),
            input_schema=t.get("input_schema"),
        )
        for t in tool_defs
    ]


@router.post(
    "/{connection_id}/refresh-tools",
    response_model=list[ConnectionToolRead],
    dependencies=[Depends(RequireScopes("connections:write"))],
)
async def refresh_connection_tools(
    connection_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Force refresh the tool list for an MCP connection."""
    from datetime import UTC, datetime

    from app.connectors.cache import connector_tool_cache
    from app.connectors.mcp_client import MCPClientError, mcp_client_pool

    conn = await _get_connection(connection_id, tenant, db)
    cd = conn.connector_definition

    if cd.connector_type != "mcp_server":
        raise HTTPException(
            status_code=400,
            detail="Tool refresh is only supported for MCP server connectors",
        )

    try:
        tools = await mcp_client_pool.discover_tools(conn, cd)
    except MCPClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        resources = await mcp_client_pool.discover_resources(conn, cd)
    except Exception:
        resources = []

    try:
        prompts = await mcp_client_pool.discover_prompts(conn, cd)
    except Exception:
        prompts = []

    conn.mcp_tools_cache = tools
    conn.mcp_resources_cache = resources
    conn.mcp_prompts_cache = prompts
    conn.cache_refreshed_at = datetime.now(UTC)
    await db.commit()

    # Invalidate Redis tool cache for this tenant
    await connector_tool_cache.invalidate(tenant.id)

    return [
        ConnectionToolRead(
            name=t.get("name", ""),
            description=t.get("description", ""),
            input_schema=t.get("inputSchema") or t.get("input_schema"),
        )
        for t in tools
    ]
