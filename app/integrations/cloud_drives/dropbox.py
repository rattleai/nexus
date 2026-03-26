"""Dropbox connector using httpx and the Dropbox API v2."""

from __future__ import annotations

import json
from urllib.parse import urlencode

import httpx
import structlog

from app.config import settings
from app.integrations.cloud_drives.base import CloudAuthResult, CloudDriveConnector, CloudFile

logger = structlog.stdlib.get_logger()

_AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
_API_BASE = "https://api.dropboxapi.com/2"
_CONTENT_BASE = "https://content.dropboxapi.com/2"


class DropboxConnector(CloudDriveConnector):
    """Dropbox integration via httpx and Dropbox HTTP API v2."""

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        params = {
            "client_id": settings.DROPBOX_APP_KEY,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "token_access_type": "offline",
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> CloudAuthResult:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "client_id": settings.DROPBOX_APP_KEY,
                    "client_secret": settings.DROPBOX_APP_SECRET,
                    "redirect_uri": redirect_uri,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            email = await self._get_account_email(client, data["access_token"])

        return CloudAuthResult(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            scopes=[],
            account_email=email,
        )

    async def refresh_access_token(self, refresh_token: str) -> CloudAuthResult:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "client_id": settings.DROPBOX_APP_KEY,
                    "client_secret": settings.DROPBOX_APP_SECRET,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            email = await self._get_account_email(client, data["access_token"])

        return CloudAuthResult(
            access_token=data["access_token"],
            refresh_token=refresh_token,
            expires_in=data.get("expires_in"),
            scopes=[],
            account_email=email,
        )

    async def list_files(
        self,
        access_token: str,
        folder_id: str | None = None,
        query: str | None = None,
    ) -> list[CloudFile]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        files: list[CloudFile] = []

        if query:
            return await self._search_files(access_token, query)

        path = folder_id if folder_id else ""
        body: dict[str, object] = {"path": path, "limit": 100}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_API_BASE}/files/list_folder",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

            files.extend(self._parse_entries(data.get("entries", [])))

            while data.get("has_more"):
                resp = await client.post(
                    f"{_API_BASE}/files/list_folder/continue",
                    headers=headers,
                    json={"cursor": data["cursor"]},
                )
                resp.raise_for_status()
                data = resp.json()
                files.extend(self._parse_entries(data.get("entries", [])))

        logger.debug("dropbox_list_files", count=len(files), folder_id=folder_id)
        return files

    async def download_file(self, access_token: str, file_id: str) -> tuple[bytes, str]:
        api_arg = json.dumps({"path": file_id})
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Dropbox-API-Arg": api_arg,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{_CONTENT_BASE}/files/download",
                headers=headers,
            )
            resp.raise_for_status()

        # Extract filename from the Dropbox-API-Result header
        result_header = resp.headers.get("Dropbox-API-Result", "{}")
        result = json.loads(result_header)
        filename = result.get("name", file_id.rsplit("/", 1)[-1])

        logger.debug("dropbox_download", file_id=file_id, filename=filename)
        return resp.content, filename

    async def get_file_metadata(self, access_token: str, file_id: str) -> CloudFile:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_API_BASE}/files/get_metadata",
                headers=headers,
                json={"path": file_id},
            )
            resp.raise_for_status()
            entry = resp.json()

        return self._parse_entry(entry)

    async def revoke_token(self, access_token: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_API_BASE}/auth/token/revoke",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                content="null",
            )
            resp.raise_for_status()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_account_email(client: httpx.AsyncClient, access_token: str) -> str:
        resp = await client.post(
            f"{_API_BASE}/users/get_current_account",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            content="null",
        )
        resp.raise_for_status()
        return resp.json().get("email", "")

    async def _search_files(self, access_token: str, query: str) -> list[CloudFile]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_API_BASE}/files/search_v2",
                headers=headers,
                json={"query": query, "options": {"max_results": 100}},
            )
            resp.raise_for_status()
            data = resp.json()

        entries = [
            match["metadata"]["metadata"]
            for match in data.get("matches", [])
            if "metadata" in match.get("metadata", {})
        ]
        return self._parse_entries(entries)

    @staticmethod
    def _parse_entry(entry: dict) -> CloudFile:
        tag = entry.get(".tag", "file")
        is_folder = tag == "folder"
        return CloudFile(
            id=entry.get("id", entry.get("path_lower", "")),
            name=entry.get("name", ""),
            mime_type=None,  # Dropbox does not return MIME types in metadata
            size=entry.get("size") if not is_folder else None,
            path=entry.get("path_display", entry.get("path_lower", "")),
            is_folder=is_folder,
            modified_at=entry.get("server_modified"),
            thumbnail_url=None,
        )

    @classmethod
    def _parse_entries(cls, entries: list[dict]) -> list[CloudFile]:
        return [cls._parse_entry(e) for e in entries]
