"""File upload/download endpoints — scoped to the authenticated tenant."""

import re
import threading
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import RateLimiter
from app.api.schemas import FileUploadResponse
from app.billing.enforcement import enforce_plan_limit, get_effective_plan
from app.config import settings
from app.core.quotas import QuotaMetric, increment_usage
from app.db.models import Tenant
from app.storage.s3 import S3Storage, StorageError, handle_storage_error

router = APIRouter(prefix="/files")
logger = structlog.stdlib.get_logger()

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")

# Shared S3 storage instance (reuses connection pool).
# Thread-safe via double-checked locking (matches s3.py pattern).

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


def _tenant_key(tenant: Tenant, filename: str) -> str:
    return f"tenants/{tenant.id}/{filename}"


@router.post(
    "",
    response_model=FileUploadResponse,
    status_code=201,
    dependencies=[
        Depends(RequireScopes("files:write")),
        Depends(RateLimiter(max_requests=settings.RATE_LIMIT_UPLOADS, key_prefix="rl:upload")),
    ],
)
async def upload_file(
    file: UploadFile,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Enforce plan quota for uploads
    plan = await get_effective_plan(tenant.id, db)
    await enforce_plan_limit(tenant.id, plan, QuotaMetric.FILE_UPLOADS_PER_DAY)

    # Read in chunks to enforce size limit without loading entire file into memory
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(65_536)  # 64KB chunks
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > settings.MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB)",
            )
        chunks.append(chunk)

    content = b"".join(chunks)

    safe_name = _sanitize_filename(file.filename or "upload")
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    key = _tenant_key(tenant, unique_name)

    try:
        storage = _get_storage()
        await storage.async_upload(key, content)
    except StorageError as exc:
        raise handle_storage_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Track usage
    await increment_usage(tenant.id, QuotaMetric.FILE_UPLOADS_PER_DAY)
    await increment_usage(tenant.id, QuotaMetric.STORAGE_BYTES, len(content))

    logger.info("file_uploaded", tenant_id=str(tenant.id), key=key, size=len(content))
    return FileUploadResponse(
        key=key,
        size=len(content),
        content_type=file.content_type or "application/octet-stream",
    )


@router.get("/{file_key:path}", dependencies=[Depends(RequireScopes("files:read"))])
async def download_file(
    file_key: str,
    tenant: Tenant = Depends(get_current_tenant),
):
    # URL-decode before validation to prevent double-encoding bypass (%2e%2e → ..)
    from urllib.parse import unquote
    file_key = unquote(file_key)

    expected_prefix = f"tenants/{tenant.id}/"
    if not file_key.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="Access denied")

    # Block path traversal
    if ".." in file_key or "\\" in file_key:
        raise HTTPException(status_code=400, detail="Invalid file key")

    try:
        storage = _get_storage()
        # Download directly — avoid TOCTOU race from separate exists check
        data = await storage.async_download(file_key)
    except StorageError as exc:
        raise handle_storage_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Extract original filename from key for Content-Disposition.
    # Escape quotes to prevent header injection.
    filename = file_key.rsplit("/", 1)[-1] if "/" in file_key else file_key
    filename_safe = filename.replace("\\", "\\\\").replace('"', '\\"')

    logger.info("file_downloaded", tenant_id=str(tenant.id), key=file_key)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename_safe}"'},
    )


@router.delete("/{file_key:path}", status_code=204, dependencies=[Depends(RequireScopes("files:write"))])
async def delete_file(
    file_key: str,
    tenant: Tenant = Depends(get_current_tenant),
):
    from urllib.parse import unquote
    file_key = unquote(file_key)

    expected_prefix = f"tenants/{tenant.id}/"
    if not file_key.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="Access denied")

    if ".." in file_key or "\\" in file_key:
        raise HTTPException(status_code=400, detail="Invalid file key")

    try:
        storage = _get_storage()
        # Delete directly — avoid TOCTOU race from separate exists check
        await storage.async_delete(file_key)
    except StorageError as exc:
        raise handle_storage_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    logger.info("file_deleted", tenant_id=str(tenant.id), key=file_key)
