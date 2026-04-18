"""Abstract DriveAdapter + shared primitives."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.credentials import CredentialManager
from app.connectors.models import (
    BrokerType,
    ConnectorDefinition,
    TenantConnection,
)

logger = structlog.stdlib.get_logger()


class DriveAdapterError(Exception):
    """Base error for drive adapters."""


class DriveFileNotFoundError(DriveAdapterError):
    """Requested file does not exist or is not accessible."""


class DriveFileTooLargeError(DriveAdapterError):
    """File exceeds ``CLOUD_DRIVE_MAX_FILE_SIZE_MB``."""


class ComposioNotSupportedError(DriveAdapterError):
    """Composio-brokered connection used where only in-house is supported.

    Cloud-drive ingest through Composio lands in a follow-up PR — the
    download actions return a mix of signed URLs and base64 payloads that
    need provider-specific handling on top of the SDK. For now, Composio
    connections surface this error and the API layer maps it to HTTP 501.
    """


@dataclass(frozen=True)
class DriveItem:
    """One row in a drive listing (folder or file)."""

    id: str
    name: str
    path: str
    is_folder: bool
    size: int | None = None
    mime_type: str | None = None
    modified_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DriveListing:
    """One page of a folder listing."""

    items: list[DriveItem]
    cursor: str | None = None


@dataclass(frozen=True)
class DriveFile:
    """A downloaded file's bytes + metadata."""

    content: bytes
    filename: str
    mime_type: str
    size: int


# ── Adapter base ────────────────────────────────────────────


class DriveAdapter(ABC):
    """Provider-specific cloud-drive operations for RAG ingest.

    One concrete subclass per provider (Dropbox, Google Drive, OneDrive).
    Registered in ``_REGISTRY`` below and resolved by connector slug.
    """

    slug: str = "abstract"
    # Preferred MIME when the provider returns a native doc that needs export.
    # Overridden only by the Google Drive adapter.
    export_mime_overrides: dict[str, tuple[str, str]] = {}

    def __init__(self, credential_manager: CredentialManager | None = None) -> None:
        self._credentials = credential_manager or CredentialManager()

    @abstractmethod
    async def list(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
        path: str = "",
        cursor: str | None = None,
    ) -> DriveListing:
        """List files and folders at ``path``. Pass ``cursor`` for pagination."""

    @abstractmethod
    async def download(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        file_id: str,
        db: AsyncSession,
    ) -> DriveFile:
        """Download one file's bytes.

        ``file_id`` is the provider-native identifier the frontend picker
        received from ``list``. For Dropbox this is a path or ``id:xxx``
        string; for Google Drive and OneDrive it's the stable file ID.
        """

    # ── Shared helpers ──────────────────────────────────────

    async def _access_token(
        self,
        *,
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
        db: AsyncSession,
    ) -> str:
        """Resolve a valid OAuth access token, refreshing if needed.

        Raises ``ComposioNotSupportedError`` when the connector is
        Composio-brokered — v1 only covers the in-house path.
        """
        if connector_def.broker == BrokerType.COMPOSIO:
            raise ComposioNotSupportedError(
                f"Composio-brokered cloud drive ingest for '{connector_def.slug}' "
                "is not yet supported. Use an in-house-brokered connection."
            )
        return await self._credentials.get_valid_token(
            connection, connector_def, db,
        )

    def _check_size_limit(self, size: int | None, filename: str) -> None:
        """Reject files larger than the configured cap before downloading.

        ``size`` may be None if the provider doesn't report it upfront; in
        that case the caller must enforce the limit post-download by
        inspecting the response body length.
        """
        if size is None:
            return
        cap_bytes = settings.CLOUD_DRIVE_MAX_FILE_SIZE_MB * 1024 * 1024
        if size > cap_bytes:
            raise DriveFileTooLargeError(
                f"File '{filename}' is {size} bytes, exceeds the "
                f"{settings.CLOUD_DRIVE_MAX_FILE_SIZE_MB} MB limit"
            )

    def _enforce_post_download_size(self, content: bytes, filename: str) -> None:
        """Fallback size check when the provider didn't report size upfront."""
        self._check_size_limit(len(content), filename)

    def _client(
        self,
        *,
        base_url: str | None = None,
        access_token: str,
        default_headers: dict[str, str] | None = None,
    ) -> httpx.AsyncClient:
        """Build an httpx client with a bearer token preset."""
        headers = {"Authorization": f"Bearer {access_token}"}
        if default_headers:
            headers.update(default_headers)
        return httpx.AsyncClient(
            base_url=base_url or "",
            headers=headers,
            timeout=httpx.Timeout(
                connect=10.0,
                read=settings.CONNECTOR_HTTP_REQUEST_TIMEOUT_SECONDS,
                write=settings.CONNECTOR_HTTP_REQUEST_TIMEOUT_SECONDS,
                pool=10.0,
            ),
            follow_redirects=True,
        )


# ── Registry ────────────────────────────────────────────────


def _build_registry() -> dict[str, type[DriveAdapter]]:
    """Lazy import the concrete adapters to avoid circular imports."""
    from app.connectors.drive.dropbox import DropboxDriveAdapter
    from app.connectors.drive.google_drive import GoogleDriveAdapter
    from app.connectors.drive.onedrive import OneDriveAdapter

    return {
        DropboxDriveAdapter.slug: DropboxDriveAdapter,
        GoogleDriveAdapter.slug: GoogleDriveAdapter,
        OneDriveAdapter.slug: OneDriveAdapter,
    }


_registry_cache: dict[str, type[DriveAdapter]] | None = None


def resolve_adapter(connector_slug: str) -> DriveAdapter:
    """Return the ``DriveAdapter`` for a connector slug.

    Raises ``DriveAdapterError`` for unknown or non-drive connectors so
    the API layer can return a clean 400.
    """
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = _build_registry()

    cls = _registry_cache.get(connector_slug)
    if cls is None:
        raise DriveAdapterError(
            f"No cloud-drive adapter registered for connector '{connector_slug}'. "
            f"Supported: {sorted(_registry_cache.keys())}"
        )
    return cls()


def supported_drive_slugs() -> frozenset[str]:
    """Slugs with a registered drive adapter — used by the frontend filter."""
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = _build_registry()
    return frozenset(_registry_cache.keys())
