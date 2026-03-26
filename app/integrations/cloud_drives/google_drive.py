"""Google Drive connector using httpx and the Drive API v3."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
import structlog

from app.config import settings
from app.integrations.cloud_drives.base import (
    CloudAuthResult,
    CloudDriveConnector,
    CloudDriveError,
    CloudFile,
    validate_resource_id,
)

logger = structlog.stdlib.get_logger()

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_API = "https://www.googleapis.com/drive/v3/files"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class GoogleDriveConnector(CloudDriveConnector):
    """Lightweight Google Drive integration via httpx (no google-api-python-client)."""

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": settings.GOOGLE_DRIVE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> CloudAuthResult:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_DRIVE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_DRIVE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            email = await self._get_user_email(client, data["access_token"])

        return CloudAuthResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            scopes=data.get("scope", "").split(),
            account_email=email,
        )

    async def refresh_access_token(self, refresh_token: str) -> CloudAuthResult:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": settings.GOOGLE_DRIVE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_DRIVE_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            email = await self._get_user_email(client, data["access_token"])

        return CloudAuthResult(
            access_token=data["access_token"],
            refresh_token=refresh_token,  # Google does not issue a new refresh token
            expires_in=data.get("expires_in"),
            scopes=data.get("scope", "").split(),
            account_email=email,
        )

    async def list_files(
        self,
        access_token: str,
        folder_id: str | None = None,
        query: str | None = None,
    ) -> list[CloudFile]:
        files: list[CloudFile] = []
        page_token: str | None = None
        headers = {"Authorization": f"Bearer {access_token}"}

        q_parts: list[str] = ["trashed = false"]
        if folder_id:
            validate_resource_id(folder_id, "folder_id")
            q_parts.append(f"'{folder_id}' in parents")
        if query:
            safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
            q_parts.append(f"name contains '{safe_query}'")
        q = " and ".join(q_parts)

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params: dict[str, str] = {
                    "q": q,
                    "fields": "nextPageToken,files(id,name,mimeType,size,parents,modifiedTime,thumbnailLink)",
                    "pageSize": "100",
                }
                if page_token:
                    params["pageToken"] = page_token

                try:
                    resp = await client.get(_DRIVE_API, headers=headers, params=params)
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise CloudDriveError("google_drive", exc.response.status_code, "list_files") from exc
                data = resp.json()

                for f in data.get("files", []):
                    is_folder = f.get("mimeType") == "application/vnd.google-apps.folder"
                    parents = f.get("parents", [])
                    path = f"/{'/'.join(parents)}/{f['name']}" if parents else f"/{f['name']}"
                    files.append(
                        CloudFile(
                            id=f["id"],
                            name=f["name"],
                            mime_type=f.get("mimeType"),
                            size=int(f["size"]) if f.get("size") else None,
                            path=path,
                            is_folder=is_folder,
                            modified_at=f.get("modifiedTime"),
                            thumbnail_url=f.get("thumbnailLink"),
                        )
                    )

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

        logger.debug("google_drive_list_files", count=len(files), folder_id=folder_id)
        return files

    async def download_file(self, access_token: str, file_id: str) -> tuple[bytes, str]:
        validate_resource_id(file_id, "file_id")
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                # Get metadata first for the filename
                meta_resp = await client.get(
                    f"{_DRIVE_API}/{file_id}",
                    headers=headers,
                    params={"fields": "name,mimeType"},
                )
                meta_resp.raise_for_status()
                meta = meta_resp.json()
                filename = meta.get("name", file_id)

                # Download content
                resp = await client.get(
                    f"{_DRIVE_API}/{file_id}",
                    headers=headers,
                    params={"alt": "media"},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise CloudDriveError("google_drive", exc.response.status_code, "download_file") from exc

        logger.debug("google_drive_download", file_id=file_id, filename=filename)
        return resp.content, filename

    async def get_file_metadata(self, access_token: str, file_id: str) -> CloudFile:
        validate_resource_id(file_id, "file_id")
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    f"{_DRIVE_API}/{file_id}",
                    headers=headers,
                    params={"fields": "id,name,mimeType,size,parents,modifiedTime,thumbnailLink"},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise CloudDriveError("google_drive", exc.response.status_code, "get_file_metadata") from exc
            f = resp.json()

        is_folder = f.get("mimeType") == "application/vnd.google-apps.folder"
        parents = f.get("parents", [])
        path = f"/{'/'.join(parents)}/{f['name']}" if parents else f"/{f['name']}"
        return CloudFile(
            id=f["id"],
            name=f["name"],
            mime_type=f.get("mimeType"),
            size=int(f["size"]) if f.get("size") else None,
            path=path,
            is_folder=is_folder,
            modified_at=f.get("modifiedTime"),
            thumbnail_url=f.get("thumbnailLink"),
        )

    async def revoke_token(self, access_token: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": access_token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise CloudDriveError("google_drive", exc.response.status_code, "revoke_token") from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_user_email(client: httpx.AsyncClient, access_token: str) -> str:
        resp = await client.get(
            _USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json().get("email", "")
