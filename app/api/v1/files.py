"""File upload/download endpoints — scoped to the authenticated tenant."""

import re
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.deps import RequireScopes, get_current_tenant
from app.api.rate_limit import RateLimiter
from app.api.schemas import FileUploadResponse
from app.config import settings
from app.db.models import Tenant
from app.storage.s3 import S3Storage, StorageError, handle_storage_error

router = APIRouter(prefix="/files")
logger = structlog.stdlib.get_logger()

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


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
):
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB)",
        )

    safe_name = _sanitize_filename(file.filename or "upload")
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    key = _tenant_key(tenant, unique_name)

    try:
        storage = S3Storage()
        await storage.async_upload(key, content)
    except StorageError as exc:
        raise handle_storage_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

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
    expected_prefix = f"tenants/{tenant.id}/"
    if not file_key.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="Access denied")

    # Block path traversal
    if ".." in file_key:
        raise HTTPException(status_code=400, detail="Invalid file key")

    try:
        storage = S3Storage()
        if not await storage.async_exists(file_key):
            raise HTTPException(status_code=404, detail="File not found")
        data = await storage.async_download(file_key)
    except StorageError as exc:
        raise handle_storage_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    logger.info("file_downloaded", tenant_id=str(tenant.id), key=file_key)
    return Response(content=data, media_type="application/octet-stream")


@router.delete("/{file_key:path}", status_code=204, dependencies=[Depends(RequireScopes("files:write"))])
async def delete_file(
    file_key: str,
    tenant: Tenant = Depends(get_current_tenant),
):
    expected_prefix = f"tenants/{tenant.id}/"
    if not file_key.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="Access denied")

    if ".." in file_key:
        raise HTTPException(status_code=400, detail="Invalid file key")

    try:
        storage = S3Storage()
        if not await storage.async_exists(file_key):
            raise HTTPException(status_code=404, detail="File not found")
        await storage.async_delete(file_key)
    except StorageError as exc:
        raise handle_storage_error(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    logger.info("file_deleted", tenant_id=str(tenant.id), key=file_key)
