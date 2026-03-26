"""Abstract base class for cloud drive connectors."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


class CloudDriveError(Exception):
    """Sanitised error from a cloud drive provider — safe to surface to users."""

    def __init__(self, provider: str, status_code: int | None, operation: str) -> None:
        self.provider = provider
        self.status_code = status_code
        self.operation = operation
        super().__init__(f"{provider}: {operation} failed (HTTP {status_code})")


# File/folder IDs are provider-specific but always alphanumeric + a few safe chars.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9!_.\-:]+$")


def validate_resource_id(value: str, label: str = "resource_id") -> None:
    """Raise ValueError if *value* contains characters unsafe for URL path interpolation."""
    if not value or not _SAFE_ID_RE.match(value):
        raise ValueError(f"Invalid {label}: must be alphanumeric (got {value!r:.60})")


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

    @abstractmethod
    async def revoke_token(self, access_token: str) -> None:
        """Best-effort revocation of the access/refresh token at the provider."""
        ...
