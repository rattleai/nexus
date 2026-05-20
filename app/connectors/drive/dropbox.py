"""Dropbox adapter — list folders and download file bytes.

Dropbox uses two API hosts:

* ``api.dropboxapi.com`` for JSON metadata endpoints (``/2/files/list_folder``).
* ``content.dropboxapi.com`` for content endpoints where the response body is
  the raw file bytes and metadata comes back in the ``Dropbox-API-Result``
  response header.
"""

from __future__ import annotations

import json
import mimetypes
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.drive.base import (
    DriveAdapter,
    DriveAdapterError,
    DriveFile,
    DriveFileNotFoundError,
    DriveItem,
    DriveListing,
)
from app.connectors.models import ConnectorDefinition, TenantConnection

logger = structlog.stdlib.get_logger()


DROPBOX_API_BASE = "https://api.dropboxapi.com"
DROPBOX_CONTENT_BASE = "https://content.dropboxapi.com"


class DropboxDriveAdapter(DriveAdapter):
    """Dropbox cloud-drive adapter."""

    slug = "dropbox"

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
            connection=connection,
            connector_def=connector_def,
            db=db,
        )

        # Dropbox continuation uses a separate endpoint; first-page and
        # subsequent-page calls have different request shapes.
        if cursor:
            url = f"{DROPBOX_API_BASE}/2/files/list_folder/continue"
            body: dict[str, Any] = {"cursor": cursor}
        else:
            url = f"{DROPBOX_API_BASE}/2/files/list_folder"
            # Dropbox requires "" for the root path, not "/".
            dropbox_path = "" if path in ("", "/") else path
            body = {
                "path": dropbox_path,
                "recursive": False,
                "include_deleted": False,
                "limit": min(settings.CLOUD_DRIVE_LIST_PAGE_SIZE, 2000),
            }

        async with self._client(access_token=token) as client:
            response = await client.post(url, json=body)

        if response.status_code == 404 or response.status_code == 409:
            # Dropbox uses 409 with an error tag for "path/not_found"
            raise DriveFileNotFoundError(f"Dropbox path '{path}' not found or inaccessible")
        response.raise_for_status()

        payload = response.json()
        items = [_entry_to_item(entry) for entry in payload.get("entries", [])]
        next_cursor = payload.get("cursor") if payload.get("has_more") else None
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
            connection=connection,
            connector_def=connector_def,
            db=db,
        )

        # Dropbox-API-Arg carries the path/id as a header-encoded JSON blob.
        arg_header = json.dumps({"path": file_id})
        headers = {
            "Dropbox-API-Arg": arg_header,
            # Must NOT send Content-Type on this endpoint.
        }

        async with self._client(access_token=token) as client:
            response = await client.post(
                f"{DROPBOX_CONTENT_BASE}/2/files/download",
                headers=headers,
            )

        if response.status_code == 409:
            raise DriveFileNotFoundError(f"Dropbox file '{file_id}' not found")
        response.raise_for_status()

        # Metadata comes back in a response header — Dropbox guarantees it.
        result_header = response.headers.get("Dropbox-API-Result")
        if not result_header:
            raise DriveAdapterError("Dropbox download response missing Dropbox-API-Result header")
        try:
            metadata = json.loads(result_header)
        except json.JSONDecodeError as exc:
            raise DriveAdapterError(f"Dropbox-API-Result is not valid JSON: {exc}") from exc

        filename = metadata.get("name") or file_id.rsplit("/", 1)[-1]
        reported_size = metadata.get("size")
        # Pre-check: Dropbox reports size in the header, so a large file
        # won't blow through httpx read before we can reject it — but we've
        # already fetched the body at this point. Accept the cost for now
        # and reject post-read; ``streamed download`` is a future optimization.
        if reported_size is not None:
            self._check_size_limit(reported_size, filename)
        content = response.content
        self._enforce_post_download_size(content, filename)

        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return DriveFile(
            content=content,
            filename=filename,
            mime_type=mime_type,
            size=len(content),
        )


# ── Helpers ─────────────────────────────────────────────────


def _entry_to_item(entry: dict[str, Any]) -> DriveItem:
    """Convert a Dropbox ``entries[*]`` payload to a ``DriveItem``.

    Dropbox tags each entry with ``.tag`` as "folder" | "file" | "deleted".
    For file downloads we prefer the stable ``id`` (e.g. "id:abc123") over
    the path, because paths change when files move.
    """
    tag = entry.get(".tag")
    is_folder = tag == "folder"
    dropbox_id = entry.get("id") or entry.get("path_lower") or ""
    name = entry.get("name", "")
    path = entry.get("path_display") or entry.get("path_lower") or ""
    size = entry.get("size") if not is_folder else None
    modified: datetime | None = None
    if raw := entry.get("server_modified"):
        try:
            # Dropbox format: "2020-01-02T03:04:05Z"
            modified = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            modified = None

    mime_type: str | None = None
    if not is_folder:
        mime_type = mimetypes.guess_type(name)[0]

    return DriveItem(
        id=dropbox_id,
        name=name,
        path=path,
        is_folder=is_folder,
        size=size,
        mime_type=mime_type,
        modified_at=modified,
        extra={"rev": entry.get("rev")} if entry.get("rev") else {},
    )
