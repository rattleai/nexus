"""MCP tools for file operations."""

from __future__ import annotations

import base64
import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.errors import not_found_error, tool_error

logger = structlog.stdlib.get_logger()


def _get_storage():
    """Get or create the shared S3 storage instance."""
    from app.storage.s3 import S3Storage

    return S3Storage()


async def file_upload(
    filename: str,
    content_base64: str,
    content_type: str = "application/octet-stream",
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Upload a file.

    Content must be base64-encoded since MCP uses JSON-RPC.
    Returns the file key and metadata.

    Example: file_upload(filename="data.csv", content_base64="...", content_type="text/csv")
    """
    try:
        file_bytes = base64.b64decode(content_base64)
    except Exception as exc:
        raise tool_error("Invalid base64 content") from exc

    from app.config import settings

    if len(file_bytes) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise tool_error(
            f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_BYTES} bytes",
            hint=f"Maximum upload size is {settings.MAX_UPLOAD_SIZE_BYTES // 1_048_576} MB.",
        )

    import re

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename.split("/")[-1])[:255] or "upload"
    key = f"tenants/{tenant.id}/{uuid.uuid4().hex}_{safe_name}"

    try:
        storage = _get_storage()
        storage.upload(key, file_bytes, content_type=content_type)
    except Exception as exc:
        raise tool_error(f"Upload failed: {exc}") from exc

    return {
        "key": key,
        "filename": safe_name,
        "size_bytes": len(file_bytes),
        "content_type": content_type,
    }


async def file_download(
    file_key: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Download a file by its key.

    Returns base64-encoded content. Only files belonging to your tenant
    can be downloaded.
    """
    expected_prefix = f"tenants/{tenant.id}/"
    if not file_key.startswith(expected_prefix):
        raise tool_error("Access denied: file belongs to a different tenant")

    try:
        storage = _get_storage()
        data = storage.download(file_key)
    except Exception as exc:
        raise not_found_error("File") from exc

    return {
        "key": file_key,
        "content_base64": base64.b64encode(data).decode(),
        "size_bytes": len(data),
    }


async def file_list(
    prefix: str | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> list[dict]:
    """List uploaded files for the current tenant.

    Optionally filter by prefix within the tenant's namespace.
    """
    tenant_prefix = f"tenants/{tenant.id}/"
    full_prefix = tenant_prefix
    if prefix:
        full_prefix = f"{tenant_prefix}{prefix}"

    try:
        storage = _get_storage()
        keys = storage.list_objects(full_prefix)
    except Exception:
        return []

    return [
        {"key": k, "filename": k.split("/")[-1]}
        for k in keys
    ]
