"""Cloud connection management: OAuth flows, file browsing, and import."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.apps.cpq.api.schemas_datasource import CloudConnectionRead
from app.config import settings
from app.core.audit import AuditAction, emit_audit_event
from app.core.encryption import decrypt, encrypt
from app.core.tenant import tenant_query
from app.db.models import Tenant
from app.db.models.datasource import (
    CloudConnection,
    CloudProvider,
    DataSource,
    DataSourceStatus,
    DataSourceType,
)
from app.integrations.cloud_drives import (
    CloudDriveConnector,
    DropboxConnector,
    GoogleDriveConnector,
    OneDriveConnector,
)
from app.integrations.cloud_drives.base import CloudFile

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/cloud-connections", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()


# ── Request / response schemas ────────────────────────────


class OAuthStartRequest(BaseModel):
    redirect_uri: str | None = Field(
        default=None,
        description="Custom redirect URI; falls back to the provider default in settings.",
    )


class OAuthStartResponse(BaseModel):
    auth_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str
    redirect_uri: str | None = None


class CloudFileResponse(BaseModel):
    id: str
    name: str
    mime_type: str | None
    size: int | None
    path: str
    is_folder: bool
    modified_at: str | None
    thumbnail_url: str | None = None


class FileImportRequest(BaseModel):
    file_ids: list[str] = Field(..., min_length=1, max_length=50)


class FileImportResult(BaseModel):
    data_source_id: uuid.UUID
    file_id: str
    name: str
    status: str


# ── Helpers ───────────────────────────────────────────────


def _get_connector(provider: str) -> CloudDriveConnector:
    """Return the appropriate connector for a cloud provider string."""
    if provider == CloudProvider.GOOGLE_DRIVE:
        return GoogleDriveConnector()
    if provider == CloudProvider.DROPBOX:
        return DropboxConnector()
    if provider == CloudProvider.ONEDRIVE:
        return OneDriveConnector()
    raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")


def _default_redirect_uri(provider: str) -> str:
    """Return the configured default redirect URI for a provider."""
    if provider == CloudProvider.GOOGLE_DRIVE:
        return settings.GOOGLE_DRIVE_REDIRECT_URI
    if provider == CloudProvider.DROPBOX:
        return settings.DROPBOX_REDIRECT_URI
    if provider == CloudProvider.ONEDRIVE:
        return settings.ONEDRIVE_REDIRECT_URI
    raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")


async def _get_connection(
    connection_id: uuid.UUID,
    tenant: Tenant,
    db: AsyncSession,
) -> CloudConnection:
    """Fetch a cloud connection scoped to the tenant, or raise 404."""
    result = await db.execute(
        tenant_query(select(CloudConnection), tenant).where(
            CloudConnection.id == connection_id,
            CloudConnection.deleted_at.is_(None),
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Cloud connection not found")
    return conn


async def _get_access_token(conn: CloudConnection, db: AsyncSession) -> str:
    """Return a valid access token, refreshing if expired.

    Persists refreshed tokens via ``db.flush()`` so changes survive the
    current transaction regardless of the caller's commit timing.
    """
    now = datetime.now(UTC)
    if conn.token_expires_at and conn.token_expires_at < now and conn.refresh_token_encrypted:
        connector = _get_connector(conn.provider)
        refresh_token = decrypt(conn.refresh_token_encrypted)
        try:
            auth_result = await connector.refresh_access_token(refresh_token)
        except Exception as exc:
            logger.error(
                "cloud_connection_token_refresh_failed",
                connection_id=str(conn.id),
                error=str(exc)[:200],
            )
            conn.is_active = False
            await db.flush()
            raise HTTPException(
                status_code=502,
                detail="Cloud connection token refresh failed. Please re-authenticate.",
            ) from exc
        conn.access_token_encrypted = encrypt(auth_result.access_token)
        if auth_result.refresh_token:
            conn.refresh_token_encrypted = encrypt(auth_result.refresh_token)
        if auth_result.expires_in:
            conn.token_expires_at = now + timedelta(seconds=auth_result.expires_in)
        await db.flush()
        logger.info("cloud_connection_token_refreshed", connection_id=str(conn.id))
    return decrypt(conn.access_token_encrypted)


# ── Endpoints ─────────────────────────────────────────────


@router.get(
    "",
    response_model=list[CloudConnectionRead],
    dependencies=[Depends(RequireScopes("datasources:read"))],
)
async def list_cloud_connections(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all cloud connections for the current tenant."""
    result = await db.execute(
        tenant_query(select(CloudConnection), tenant).where(
            CloudConnection.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())


@router.post(
    "/{provider}/auth",
    response_model=OAuthStartResponse,
    dependencies=[Depends(RequireScopes("datasources:write"))],
)
async def start_oauth_flow(
    provider: str,
    body: OAuthStartRequest | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Start the OAuth authorization flow for a cloud provider.

    Returns the authorization URL the client should redirect to and a random
    state parameter for CSRF protection.
    """
    connector = _get_connector(provider)

    # Reject custom redirect URIs -- only the server-configured URI is allowed
    # to prevent OAuth authorization code interception attacks.
    default_uri = _default_redirect_uri(provider)
    if body and body.redirect_uri and body.redirect_uri != default_uri:
        raise HTTPException(
            status_code=400,
            detail="Custom redirect URIs are not allowed. Use the configured redirect URI.",
        )
    redirect_uri = default_uri
    if not redirect_uri:
        raise HTTPException(
            status_code=400,
            detail=f"No redirect URI configured for {provider}. Set it in settings.",
        )

    state = secrets.token_urlsafe(32)

    # Store state in Redis for CSRF validation in the callback (10-min TTL).
    from app.core.redis import redis_pool

    await redis_pool.setex(f"oauth_state:{tenant.id}:{state}", 600, str(tenant.id))

    auth_url = connector.get_auth_url(redirect_uri=redirect_uri, state=state)
    logger.info("cloud_oauth_started", provider=provider, tenant_id=str(tenant.id))
    return OAuthStartResponse(auth_url=auth_url, state=state)


@router.get(
    "/{provider}/callback",
    response_model=CloudConnectionRead,
    dependencies=[Depends(RequireScopes("datasources:write"))],
)
async def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    redirect_uri: str | None = Query(default=None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback: exchange the authorization code for tokens
    and persist a new CloudConnection.
    """
    # ── Validate OAuth state (CSRF protection) ────────────
    from app.core.redis import redis_pool

    state_key = f"oauth_state:{tenant.id}:{state}"
    stored = await redis_pool.get(state_key)
    if not stored or stored != str(tenant.id):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    await redis_pool.delete(state_key)  # one-time use

    connector = _get_connector(provider)
    # Only allow the configured redirect URI (mirrors start_oauth_flow validation)
    effective_redirect_uri = _default_redirect_uri(provider)
    if redirect_uri and redirect_uri != effective_redirect_uri:
        raise HTTPException(status_code=400, detail="Custom redirect URIs are not allowed")
    if not effective_redirect_uri:
        raise HTTPException(status_code=400, detail=f"No redirect URI for {provider}")

    try:
        auth_result = await connector.exchange_code(code, effective_redirect_uri)
    except Exception as exc:
        logger.error("cloud_oauth_exchange_failed", provider=provider, error=str(exc)[:200])
        raise HTTPException(status_code=502, detail="Failed to exchange authorization code with provider") from exc

    now = datetime.now(UTC)
    conn = CloudConnection(
        tenant_id=tenant.id,
        provider=CloudProvider(provider),
        account_email=auth_result.account_email,
        display_name=auth_result.account_email,
        access_token_encrypted=encrypt(auth_result.access_token),
        refresh_token_encrypted=encrypt(auth_result.refresh_token) if auth_result.refresh_token else None,
        token_expires_at=now + timedelta(seconds=auth_result.expires_in) if auth_result.expires_in else None,
        scopes={"scopes": auth_result.scopes} if auth_result.scopes else None,
        is_active=True,
    )
    db.add(conn)
    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="cloud_connection",
        resource_id=str(conn.id),
        tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(conn)
    logger.info(
        "cloud_connection_created",
        provider=provider,
        connection_id=str(conn.id),
        tenant_id=str(tenant.id),
        email=auth_result.account_email,
    )
    return conn


@router.delete(
    "/{connection_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("datasources:write"))],
)
async def delete_cloud_connection(
    connection_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete (revoke) a cloud connection."""
    conn = await _get_connection(connection_id, tenant, db)

    # Best-effort: revoke the token at the provider so it cannot be reused.
    try:
        connector = _get_connector(conn.provider)
        access_token = decrypt(conn.access_token_encrypted)
        await connector.revoke_token(access_token)
    except Exception:
        logger.warning("cloud_token_revocation_failed", connection_id=str(connection_id))

    conn.deleted_at = datetime.now(UTC)
    conn.is_active = False
    # Clear encrypted credentials as defense-in-depth.
    conn.access_token_encrypted = ""
    conn.refresh_token_encrypted = None
    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="cloud_connection",
        resource_id=str(conn.id),
        tenant_id=tenant.id,
    )
    await db.commit()
    logger.info("cloud_connection_deleted", connection_id=str(connection_id), tenant_id=str(tenant.id))


@router.get(
    "/{connection_id}/files",
    response_model=list[CloudFileResponse],
    dependencies=[Depends(RequireScopes("datasources:read"))],
)
async def browse_files(
    connection_id: uuid.UUID,
    folder_id: str | None = Query(default=None),
    query: str | None = Query(default=None, max_length=255),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Browse files in a connected cloud drive.

    Optionally filter by folder or search query.
    """
    conn = await _get_connection(connection_id, tenant, db)
    connector = _get_connector(conn.provider)
    access_token = await _get_access_token(conn, db)

    try:
        files = await connector.list_files(access_token, folder_id=folder_id, query=query)
    except Exception as exc:
        logger.error(
            "cloud_browse_failed",
            connection_id=str(connection_id),
            error=str(exc)[:200],
        )
        raise HTTPException(status_code=502, detail="Failed to list files from cloud provider") from exc

    await db.commit()

    return [
        CloudFileResponse(
            id=f.id,
            name=f.name,
            mime_type=f.mime_type,
            size=f.size,
            path=f.path,
            is_folder=f.is_folder,
            modified_at=f.modified_at,
            thumbnail_url=f.thumbnail_url,
        )
        for f in files
    ]


@router.post(
    "/{connection_id}/import",
    response_model=list[FileImportResult],
    status_code=201,
    dependencies=[Depends(RequireScopes("datasources:write"))],
)
async def import_files(
    connection_id: uuid.UUID,
    body: FileImportRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Import selected cloud files as DataSources.

    Creates a DataSource record for each file in PENDING status.  Actual
    downloading and extraction should be handled asynchronously by a worker.
    """
    conn = await _get_connection(connection_id, tenant, db)
    connector = _get_connector(conn.provider)
    access_token = await _get_access_token(conn, db)

    results: list[FileImportResult] = []
    for file_id in body.file_ids:
        try:
            meta: CloudFile = await connector.get_file_metadata(access_token, file_id)
        except Exception as exc:
            logger.warning(
                "cloud_import_metadata_failed",
                file_id=file_id,
                connection_id=str(connection_id),
                error=str(exc)[:200],
            )
            continue

        if meta.is_folder:
            logger.info("cloud_import_skip_folder", file_id=file_id, name=meta.name)
            continue

        # Validate file size (100 MB limit)
        _MAX_IMPORT_SIZE = 100_000_000
        if meta.size and meta.size > _MAX_IMPORT_SIZE:
            logger.warning("cloud_import_file_too_large", file_id=file_id, size=meta.size)
            continue

        # Validate MIME type against allowlist
        _ALLOWED_IMPORT_MIMES = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "text/csv",
            "application/json",
            "text/plain",
            "text/html",
            "application/vnd.oasis.opendocument.spreadsheet",
            "application/vnd.oasis.opendocument.text",
        }
        if meta.mime_type and meta.mime_type not in _ALLOWED_IMPORT_MIMES:
            logger.warning("cloud_import_unsupported_type", file_id=file_id, mime=meta.mime_type)
            continue

        ds = DataSource(
            tenant_id=tenant.id,
            name=meta.name,
            source_type=DataSourceType.CLOUD_DRIVE,
            status=DataSourceStatus.PENDING,
            filename=meta.name,
            mime_type=meta.mime_type,
            file_size=meta.size,
            cloud_provider=CloudProvider(conn.provider),
            cloud_connection_id=conn.id,
            cloud_file_id=meta.id,
            metadata_={
                "cloud_path": meta.path,
                "cloud_modified_at": meta.modified_at,
            },
        )
        db.add(ds)
        await db.flush()  # Assign the UUID

        await emit_audit_event(
            db,
            action=AuditAction.CREATE,
            resource_type="data_source",
            resource_id=str(ds.id),
            tenant_id=tenant.id,
            changes={"imported_from": conn.provider, "cloud_file_id": file_id},
        )

        results.append(
            FileImportResult(
                data_source_id=ds.id,
                file_id=meta.id,
                name=meta.name,
                status=DataSourceStatus.PENDING,
            )
        )

    await db.commit()
    logger.info(
        "cloud_import_complete",
        connection_id=str(connection_id),
        tenant_id=str(tenant.id),
        imported=len(results),
        requested=len(body.file_ids),
    )
    return results
