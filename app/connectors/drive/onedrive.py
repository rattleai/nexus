"""OneDrive adapter — list and download via Microsoft Graph.

The ``/me/drive/items/{id}/content`` endpoint returns a 302 redirect to a
pre-signed download URL; httpx follows redirects by default so the body
comes back as raw bytes in the final response.
"""

from __future__ import annotations

import mimetypes
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.drive.base import (
    DriveAdapter,
    DriveFile,
    DriveFileNotFoundError,
    DriveItem,
    DriveListing,
)
from app.connectors.models import ConnectorDefinition, TenantConnection

logger = structlog.stdlib.get_logger()


GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class OneDriveAdapter(DriveAdapter):
    """OneDrive (Microsoft Graph) cloud-drive adapter."""

    slug = "onedrive"

    async def list(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
        path: str = "",
        cursor: str | None = None,
    ) -> DriveListing:
        token = await self._access_token(
            connection=connection, connector_def=connector_def, db=db,
        )

        # If the caller passed an ``@odata.nextLink`` URL as cursor, hit it
        # directly (it already encodes pagination state). Otherwise compose
        # the children-of endpoint from ``path`` (treated as parent ID).
        if cursor:
            url = cursor
            params: dict[str, Any] = {}
        elif path and path != "root":
            url = f"{GRAPH_API_BASE}/me/drive/items/{path}/children"
            params = {
                "$top": min(settings.CLOUD_DRIVE_LIST_PAGE_SIZE, 200),
                "$select": "id,name,folder,file,size,lastModifiedDateTime,parentReference",
                "$orderby": "name asc",
            }
        else:
            url = f"{GRAPH_API_BASE}/me/drive/root/children"
            params = {
                "$top": min(settings.CLOUD_DRIVE_LIST_PAGE_SIZE, 200),
                "$select": "id,name,folder,file,size,lastModifiedDateTime,parentReference",
                "$orderby": "name asc",
            }

        async with self._client(access_token=token) as client:
            response = await client.get(url, params=params)

        if response.status_code == 404:
            raise DriveFileNotFoundError(f"OneDrive path '{path}' not found")
        response.raise_for_status()
        payload = response.json()

        items = [_item_to_drive_item(entry) for entry in payload.get("value", [])]
        next_cursor = payload.get("@odata.nextLink")
        return DriveListing(items=items, cursor=next_cursor)

    async def download(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        file_id: str,
        db: AsyncSession,
    ) -> DriveFile:
        token = await self._access_token(
            connection=connection, connector_def=connector_def, db=db,
        )

        async with self._client(access_token=token) as client:
            # Fetch metadata so we have filename + size before downloading.
            meta_resp = await client.get(
                f"{GRAPH_API_BASE}/me/drive/items/{file_id}",
                params={
                    "$select": "id,name,size,file,lastModifiedDateTime",
                },
            )
            if meta_resp.status_code == 404:
                raise DriveFileNotFoundError(
                    f"OneDrive file '{file_id}' not found"
                )
            meta_resp.raise_for_status()
            meta = meta_resp.json()

            filename = meta.get("name") or file_id
            reported_size = meta.get("size")
            if reported_size is not None:
                self._check_size_limit(int(reported_size), filename)

            # /content returns 302 to a pre-signed URL; httpx follows it.
            content_resp = await client.get(
                f"{GRAPH_API_BASE}/me/drive/items/{file_id}/content",
            )
            content_resp.raise_for_status()
            content = content_resp.content

        self._enforce_post_download_size(content, filename)

        # Prefer the server-reported MIME (meta.file.mimeType); fall back
        # to the response header, then to the filename extension.
        file_info = meta.get("file", {}) or {}
        mime_type = (
            file_info.get("mimeType")
            or content_resp.headers.get("Content-Type", "").split(";")[0].strip()
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        return DriveFile(
            content=content,
            filename=filename,
            mime_type=mime_type,
            size=len(content),
        )


# ── Helpers ─────────────────────────────────────────────────


def _item_to_drive_item(entry: dict[str, Any]) -> DriveItem:
    is_folder = "folder" in entry
    modified: datetime | None = None
    if raw := entry.get("lastModifiedDateTime"):
        try:
            modified = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            modified = None
    size: int | None = None
    if not is_folder and entry.get("size") is not None:
        try:
            size = int(entry["size"])
        except (TypeError, ValueError):
            size = None
    mime_type: str | None = None
    if not is_folder:
        mime_type = (entry.get("file") or {}).get("mimeType") or mimetypes.guess_type(
            entry.get("name", "")
        )[0]

    return DriveItem(
        id=entry.get("id", ""),
        name=entry.get("name", ""),
        # Graph items are navigated by ID; we store the ID in ``path`` too
        # so the frontend can use it as the ``path`` arg for child listings.
        path=entry.get("id", ""),
        is_folder=is_folder,
        size=size,
        mime_type=mime_type,
        modified_at=modified,
        extra={
            "parent_id": (entry.get("parentReference") or {}).get("id"),
        },
    )
