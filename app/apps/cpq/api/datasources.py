"""Data source CRUD, reprocessing, chunk listing, and semantic search endpoints."""

import re
import threading
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.apps.cpq.api.schemas_datasource import (
    DataSourceChunkRead,
    DataSourceCreate,
    DataSourceRead,
    DataSourceSearchRequest,
    DataSourceSearchResult,
    ExtractionPreview,
)
from app.config import settings
from app.core.audit import AuditAction, emit_audit_event
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.db.models import (
    DataSource,
    DataSourceChunk,
    DataSourceStatus,
    DataSourceType,
    Tenant,
)
from app.storage.s3 import S3Storage, StorageError, handle_storage_error

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/datasources", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")

# Shared S3 storage instance (reuses connection pool).
# Thread-safe via double-checked locking (matches files.py pattern).
_storage: S3Storage | None = None
_storage_lock = threading.Lock()


def _get_storage() -> S3Storage:
    global _storage
    if _storage is None:
        with _storage_lock:
            if _storage is None:
                _storage = S3Storage()
    return _storage


def _sanitize_filename(name: str) -> str:
    """Strip path components and unsafe characters from a filename."""
    name = name.split("/")[-1].split("\\")[-1]
    name = _SAFE_FILENAME_RE.sub("_", name)
    return name[:255] or "upload"


# ── Create ───────────────────────────────────────────────


@router.post(
    "",
    response_model=DataSourceRead,
    status_code=201,
    dependencies=[Depends(RequireScopes("datasources:write"))],
)
async def create_datasource(
    body: DataSourceCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a new data source from a URL, cloud drive reference, or pasted text.

    For file uploads, use POST /datasources/upload instead.
    """
    # Verify connection belongs to this tenant (prevent cross-tenant reference)
    if body.cloud_connection_id:
        from app.connectors.models import TenantConnection

        cc_result = await db.execute(
            tenant_query(select(TenantConnection), tenant).where(
                TenantConnection.id == body.cloud_connection_id,
                TenantConnection.deleted_at.is_(None),
            )
        )
        if not cc_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Connection not found")

    ds = DataSource(
        tenant_id=tenant.id,
        name=body.name,
        source_type=DataSourceType(body.source_type),
        status=DataSourceStatus.PENDING,
        filename=body.filename,
        mime_type=body.mime_type,
        file_size=body.file_size,
        url=body.url,
        connector_slug=body.cloud_provider,
        connection_id=body.cloud_connection_id,
        cloud_file_id=body.cloud_file_id,
        metadata_=body.metadata or {},
    )

    # For paste sources, store content directly as the first chunk after commit
    paste_content = body.content if body.source_type == "paste" else None

    db.add(ds)
    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="data_source",
        resource_id=str(ds.id),
        tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(ds)

    # For paste sources, create the initial chunk inline
    if paste_content:
        chunk = DataSourceChunk(
            tenant_id=tenant.id,
            data_source_id=ds.id,
            chunk_index=0,
            content=paste_content,
        )
        db.add(chunk)
        ds.chunk_count = 1
        ds.status = DataSourceStatus.READY
        await db.commit()
        await db.refresh(ds)

    # TODO: Trigger async extraction via Celery for non-paste sources
    # if ds.source_type != DataSourceType.PASTE:
    #     from app.tasks.extraction import extract_datasource
    #     extract_datasource.delay(str(ds.id))

    logger.info("datasource_created", tenant_id=str(tenant.id), datasource_id=str(ds.id), source_type=ds.source_type)
    return ds


# ── Upload ───────────────────────────────────────────────


@router.post(
    "/upload",
    response_model=DataSourceRead,
    status_code=201,
    dependencies=[Depends(RequireScopes("datasources:write"))],
)
async def upload_datasource(
    file: UploadFile,
    name: str = Query(..., min_length=1, max_length=255),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a data source by uploading a file.

    The file is stored in S3 and extraction is triggered asynchronously.
    """
    safe_name = _sanitize_filename(file.filename or "upload")
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    key = f"tenants/{tenant.id}/datasources/{unique_name}"

    try:
        storage = _get_storage()
        total_size = await storage.async_upload_fileobj(
            key, file.file, max_size=settings.MAX_UPLOAD_SIZE_BYTES
        )
    except StorageError as exc:
        raise handle_storage_error(exc) from exc
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Storage service unavailable") from None

    ds = DataSource(
        tenant_id=tenant.id,
        name=name,
        source_type=DataSourceType.UPLOAD,
        status=DataSourceStatus.PENDING,
        file_key=key,
        filename=safe_name,
        mime_type=file.content_type or "application/octet-stream",
        file_size=total_size,
        metadata_={},
    )
    db.add(ds)
    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="data_source",
        resource_id=str(ds.id),
        tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(ds)

    # TODO: Trigger async extraction via Celery
    # from app.tasks.extraction import extract_datasource
    # extract_datasource.delay(str(ds.id))

    logger.info(
        "datasource_uploaded",
        tenant_id=str(tenant.id),
        datasource_id=str(ds.id),
        key=key,
        size=total_size,
    )
    return ds


# ── List ─────────────────────────────────────────────────


@router.get(
    "",
    response_model=CursorPage[DataSourceRead],
    dependencies=[Depends(RequireScopes("datasources:read"))],
)
async def list_datasources(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    source_type: str | None = None,
    status: str | None = None,
    search: str | None = Query(default=None, max_length=255),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List data sources with cursor pagination and optional filters."""
    stmt = tenant_query(select(DataSource), tenant).where(DataSource.deleted_at.is_(None))
    if source_type:
        stmt = stmt.where(DataSource.source_type == DataSourceType(source_type))
    if status:
        stmt = stmt.where(DataSource.status == DataSourceStatus(status))
    if search:
        from app.core.query_utils import escape_like

        stmt = stmt.where(DataSource.name.ilike(f"%{escape_like(search)}%"))
    return await paginate(db, stmt, DataSource.created_at, limit=limit, cursor=cursor, descending=True)


# ── Get with extraction preview ──────────────────────────


@router.get(
    "/{datasource_id}",
    response_model=ExtractionPreview,
    dependencies=[Depends(RequireScopes("datasources:read"))],
)
async def get_datasource(
    datasource_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get a data source with extraction preview (sample chunks and detected entities)."""
    result = await db.execute(
        tenant_query(select(DataSource), tenant).where(
            DataSource.id == datasource_id, DataSource.deleted_at.is_(None)
        )
    )
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    # Fetch first few chunks as a preview (explicit tenant check for defense-in-depth)
    chunks_result = await db.execute(
        select(DataSourceChunk)
        .where(
            DataSourceChunk.data_source_id == datasource_id,
            DataSourceChunk.tenant_id == tenant.id,
        )
        .order_by(DataSourceChunk.chunk_index)
        .limit(5)
    )
    sample_chunks = list(chunks_result.scalars().all())

    # Extract detected entities from extraction_result if available
    detected_entities: dict[str, int] = {}
    if ds.extraction_result and isinstance(ds.extraction_result, dict):
        detected_entities = ds.extraction_result.get("detected_entities", {})

    return ExtractionPreview(
        data_source_id=ds.id,
        data_source_name=ds.name,
        status=ds.status,
        chunk_count=ds.chunk_count,
        detected_entities=detected_entities,
        sample_chunks=sample_chunks,
        extraction_error=ds.extraction_error,
    )


# ── Delete (soft) ────────────────────────────────────────


@router.delete(
    "/{datasource_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("datasources:write"))],
)
async def delete_datasource(
    datasource_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a data source."""
    result = await db.execute(
        tenant_query(select(DataSource), tenant).where(
            DataSource.id == datasource_id, DataSource.deleted_at.is_(None)
        )
    )
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")
    ds.deleted_at = datetime.now(UTC)
    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="data_source",
        resource_id=str(ds.id),
        tenant_id=tenant.id,
    )
    await db.commit()


# ── Reprocess ────────────────────────────────────────────


@router.post(
    "/{datasource_id}/reprocess",
    response_model=DataSourceRead,
    dependencies=[Depends(RequireScopes("datasources:write"))],
)
async def reprocess_datasource(
    datasource_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Re-trigger extraction for a data source.

    Resets the status to PENDING and clears previous extraction errors.
    Existing chunks are deleted so they can be regenerated.
    """
    result = await db.execute(
        tenant_query(select(DataSource), tenant).where(
            DataSource.id == datasource_id, DataSource.deleted_at.is_(None)
        )
    )
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    # Bulk-delete existing chunks (tenant filter for defense-in-depth)
    await db.execute(
        delete(DataSourceChunk).where(
            DataSourceChunk.data_source_id == datasource_id,
            DataSourceChunk.tenant_id == tenant.id,
        )
    )

    # Reset extraction state
    ds.status = DataSourceStatus.PENDING
    ds.extraction_error = None
    ds.extraction_result = None
    ds.chunk_count = 0

    await emit_audit_event(
        db,
        action=AuditAction.UPDATE,
        resource_type="data_source",
        resource_id=str(ds.id),
        tenant_id=tenant.id,
        changes={"action": "reprocess"},
    )
    await db.commit()
    await db.refresh(ds)

    # TODO: Trigger async extraction via Celery
    # from app.tasks.extraction import extract_datasource
    # extract_datasource.delay(str(ds.id))

    logger.info("datasource_reprocess", tenant_id=str(tenant.id), datasource_id=str(ds.id))
    return ds


# ── Chunks ───────────────────────────────────────────────


@router.get(
    "/{datasource_id}/chunks",
    response_model=CursorPage[DataSourceChunkRead],
    dependencies=[Depends(RequireScopes("datasources:read"))],
)
async def list_chunks(
    datasource_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List indexed chunks for a data source with cursor pagination."""
    # Verify data source exists and belongs to tenant
    result = await db.execute(
        tenant_query(select(DataSource), tenant).where(
            DataSource.id == datasource_id, DataSource.deleted_at.is_(None)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Data source not found")

    stmt = select(DataSourceChunk).where(
        DataSourceChunk.data_source_id == datasource_id,
        DataSourceChunk.tenant_id == tenant.id,
    )
    return await paginate(db, stmt, DataSourceChunk.created_at, limit=limit, cursor=cursor, descending=False)


# ── Semantic Search ──────────────────────────────────────


@router.post(
    "/search",
    response_model=list[DataSourceSearchResult],
    dependencies=[Depends(RequireScopes("datasources:read"))],
)
async def search_datasources(
    body: DataSourceSearchRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search across data source chunks.

    Returns matched chunks ranked by relevance. When embeddings are
    available, vector similarity is used. Otherwise falls back to basic
    text matching (ILIKE).
    """
    stmt = (
        select(DataSourceChunk, DataSource.name.label("ds_name"))
        .join(DataSource, DataSourceChunk.data_source_id == DataSource.id)
        .where(
            DataSource.tenant_id == tenant.id,
            DataSource.deleted_at.is_(None),
            DataSource.status == DataSourceStatus.READY,
        )
    )

    # Optionally filter to specific data sources
    if body.data_source_ids:
        stmt = stmt.where(DataSource.id.in_(body.data_source_ids))

    # Fallback: basic ILIKE text search (vector search can be added when
    # an embedding service / pgvector is integrated)
    from app.core.query_utils import escape_like

    stmt = stmt.where(DataSourceChunk.content.ilike(f"%{escape_like(body.query)}%"))
    stmt = stmt.limit(body.top_k)

    result = await db.execute(stmt)
    rows = result.all()

    results = []
    for row in rows:
        chunk = row[0]
        ds_name = row[1]
        results.append(
            DataSourceSearchResult(
                chunk_id=chunk.id,
                data_source_id=chunk.data_source_id,
                data_source_name=ds_name,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                section_title=chunk.section_title,
                table_index=chunk.table_index,
                score=1.0,  # Placeholder until vector similarity is implemented
            )
        )

    return results
