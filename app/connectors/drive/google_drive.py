"""Google Drive adapter — list, download, and export native Google docs.

Native Google-Workspace documents (Docs, Sheets, Slides, Forms, Drawings)
cannot be downloaded with ``alt=media``; they must be exported to a
binary-friendly format via ``/files/{id}/export?mimeType=...``. The mapping
is conservative: Docs → DOCX, Sheets → XLSX, Slides → PPTX, Drawings → PNG.
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


GOOGLE_API_BASE = "https://www.googleapis.com"

# Google-native MIME → (export MIME, file extension)
GOOGLE_NATIVE_EXPORTS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", "png"),
    "application/vnd.google-apps.script": ("application/vnd.google-apps.script+json", "json"),
}

# Fields returned on listing — minimal but sufficient for the picker.
_LIST_FIELDS = "files(id,name,mimeType,size,modifiedTime,parents),nextPageToken"


class GoogleDriveAdapter(DriveAdapter):
    """Google Drive (v3) cloud-drive adapter."""

    slug = "google-workspace"
    export_mime_overrides = GOOGLE_NATIVE_EXPORTS

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

        # ``path`` here is actually a parent folder ID (Google Drive has no
        # filesystem paths the way Dropbox does). The root is aliased as
        # "root" by the Drive API.
        parent_id = path if path else "root"

        params: dict[str, Any] = {
            "q": f"'{parent_id}' in parents and trashed = false",
            "fields": _LIST_FIELDS,
            "pageSize": min(settings.CLOUD_DRIVE_LIST_PAGE_SIZE, 1000),
            "orderBy": "folder,name",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if cursor:
            params["pageToken"] = cursor

        async with self._client(
            base_url=GOOGLE_API_BASE,
            access_token=token,
        ) as client:
            response = await client.get("/drive/v3/files", params=params)

        if response.status_code == 404:
            raise DriveFileNotFoundError(f"Google Drive folder '{parent_id}' not found")
        response.raise_for_status()
        payload = response.json()

        items = [_file_to_item(entry) for entry in payload.get("files", [])]
        next_cursor = payload.get("nextPageToken")
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

        # First fetch metadata so we know whether to ``?alt=media`` or
        # ``/export?mimeType=...`` and what filename to use.
        async with self._client(
            base_url=GOOGLE_API_BASE,
            access_token=token,
        ) as client:
            meta_resp = await client.get(
                f"/drive/v3/files/{file_id}",
                params={
                    "fields": "id,name,mimeType,size,modifiedTime",
                    "supportsAllDrives": "true",
                },
            )
            if meta_resp.status_code == 404:
                raise DriveFileNotFoundError(f"Google Drive file '{file_id}' not found")
            meta_resp.raise_for_status()
            meta = meta_resp.json()

            mime_type: str = meta.get("mimeType", "application/octet-stream")
            filename: str = meta.get("name") or file_id
            reported_size = int(meta["size"]) if meta.get("size") else None
            if reported_size is not None:
                self._check_size_limit(reported_size, filename)

            # Google native docs → export; regular files → alt=media.
            if mime_type in GOOGLE_NATIVE_EXPORTS:
                export_mime, ext = GOOGLE_NATIVE_EXPORTS[mime_type]
                if not filename.endswith(f".{ext}"):
                    filename = f"{filename}.{ext}"
                content_resp = await client.get(
                    f"/drive/v3/files/{file_id}/export",
                    params={"mimeType": export_mime},
                )
                final_mime = export_mime
            else:
                content_resp = await client.get(
                    f"/drive/v3/files/{file_id}",
                    params={"alt": "media", "supportsAllDrives": "true"},
                )
                final_mime = mime_type or (mimetypes.guess_type(filename)[0] or "application/octet-stream")

            content_resp.raise_for_status()
            content = content_resp.content

        self._enforce_post_download_size(content, filename)
        return DriveFile(
            content=content,
            filename=filename,
            mime_type=final_mime,
            size=len(content),
        )


# ── Helpers ─────────────────────────────────────────────────


def _file_to_item(entry: dict[str, Any]) -> DriveItem:
    mime_type = entry.get("mimeType", "")
    is_folder = mime_type == "application/vnd.google-apps.folder"
    modified: datetime | None = None
    if raw := entry.get("modifiedTime"):
        try:
            modified = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            modified = None
    size: int | None = None
    if not is_folder and entry.get("size"):
        try:
            size = int(entry["size"])
        except (TypeError, ValueError):
            size = None
    return DriveItem(
        id=entry.get("id", ""),
        name=entry.get("name", ""),
        # Google Drive doesn't return paths; the frontend uses id navigation.
        path=entry.get("id", ""),
        is_folder=is_folder,
        size=size,
        mime_type=mime_type or None,
        modified_at=modified,
        extra={"parents": entry.get("parents", [])},
    )
