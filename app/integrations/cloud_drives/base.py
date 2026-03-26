"""Abstract base class for cloud drive connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CloudFile:
    id: str  # Provider-specific file ID
    name: str
    mime_type: str | None
    size: int | None  # bytes
    path: str  # Full path in drive
    is_folder: bool
    modified_at: str | None
    thumbnail_url: str | None = None


@dataclass
class CloudAuthResult:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    scopes: list[str]
    account_email: str


class CloudDriveConnector(ABC):
    @abstractmethod
    def get_auth_url(self, redirect_uri: str, state: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> CloudAuthResult: ...

    @abstractmethod
    async def refresh_access_token(self, refresh_token: str) -> CloudAuthResult: ...

    @abstractmethod
    async def list_files(
        self,
        access_token: str,
        folder_id: str | None = None,
        query: str | None = None,
    ) -> list[CloudFile]: ...

    @abstractmethod
    async def download_file(self, access_token: str, file_id: str) -> tuple[bytes, str]: ...

    @abstractmethod
    async def get_file_metadata(self, access_token: str, file_id: str) -> CloudFile: ...
