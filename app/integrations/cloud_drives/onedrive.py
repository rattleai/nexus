"""OneDrive / Microsoft Graph connector using httpx."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx
import structlog

from app.config import settings
from app.integrations.cloud_drives.base import CloudAuthResult, CloudDriveConnector, CloudFile

logger = structlog.stdlib.get_logger()

_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
_GRAPH_API = "https://graph.microsoft.com/v1.0"
_SCOPES = "Files.Read.All User.Read offline_access"


class OneDriveConnector(CloudDriveConnector):
    """OneDrive integration via Microsoft Graph API and httpx."""

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": settings.ONEDRIVE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "state": state,
            "response_mode": "query",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> CloudAuthResult:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.ONEDRIVE_CLIENT_ID,
                    "client_secret": settings.ONEDRIVE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "scope": _SCOPES,
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
                    "client_id": settings.ONEDRIVE_CLIENT_ID,
                    "client_secret": settings.ONEDRIVE_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "scope": _SCOPES,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            email = await self._get_user_email(client, data["access_token"])

        return CloudAuthResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
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
        headers = {"Authorization": f"Bearer {access_token}"}
        files: list[CloudFile] = []

        if query:
            url = f"{_GRAPH_API}/me/drive/root/search(q='{query}')"
        elif folder_id:
            url = f"{_GRAPH_API}/me/drive/items/{folder_id}/children"
        else:
            url = f"{_GRAPH_API}/me/drive/root/children"

        async with httpx.AsyncClient(timeout=30) as client:
            while url:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("value", []):
                    is_folder = "folder" in item
                    parent_path = item.get("parentReference", {}).get("path", "")
                    path = f"{parent_path}/{item['name']}" if parent_path else f"/{item['name']}"
                    files.append(
                        CloudFile(
                            id=item["id"],
                            name=item["name"],
                            mime_type=item.get("file", {}).get("mimeType"),
                            size=item.get("size"),
                            path=path,
                            is_folder=is_folder,
                            modified_at=item.get("lastModifiedDateTime"),
                            thumbnail_url=None,
                        )
                    )

                url = data.get("@odata.nextLink")

        logger.debug("onedrive_list_files", count=len(files), folder_id=folder_id)
        return files

    async def download_file(self, access_token: str, file_id: str) -> tuple[bytes, str]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            # Get metadata for the filename
            meta_resp = await client.get(
                f"{_GRAPH_API}/me/drive/items/{file_id}",
                headers=headers,
            )
            meta_resp.raise_for_status()
            meta = meta_resp.json()
            filename = meta.get("name", file_id)

            # Download content (Graph returns a 302 redirect to the actual file)
            resp = await client.get(
                f"{_GRAPH_API}/me/drive/items/{file_id}/content",
                headers=headers,
            )
            resp.raise_for_status()

        logger.debug("onedrive_download", file_id=file_id, filename=filename)
        return resp.content, filename

    async def get_file_metadata(self, access_token: str, file_id: str) -> CloudFile:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{_GRAPH_API}/me/drive/items/{file_id}",
                headers=headers,
            )
            resp.raise_for_status()
            item = resp.json()

        is_folder = "folder" in item
        parent_path = item.get("parentReference", {}).get("path", "")
        path = f"{parent_path}/{item['name']}" if parent_path else f"/{item['name']}"
        return CloudFile(
            id=item["id"],
            name=item["name"],
            mime_type=item.get("file", {}).get("mimeType"),
            size=item.get("size"),
            path=path,
            is_folder=is_folder,
            modified_at=item.get("lastModifiedDateTime"),
            thumbnail_url=None,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_user_email(client: httpx.AsyncClient, access_token: str) -> str:
        resp = await client.get(
            f"{_GRAPH_API}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("mail") or data.get("userPrincipalName", "")
