"""Unit tests for cloud-drive adapters (Dropbox / Google Drive / OneDrive).

Adapter internals are exercised end-to-end with a mocked httpx client so the
real network is never touched. The mocked client records every request the
adapter makes and returns scripted responses, letting us assert both the
output shape (DriveListing / DriveFile) and the wire-level behavior
(correct base URL, headers, query params).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.connectors.drive import (
    ComposioNotSupportedError,
    DriveFile,
    DriveFileNotFoundError,
    DriveListing,
)
from app.connectors.drive.dropbox import DropboxDriveAdapter
from app.connectors.drive.google_drive import GoogleDriveAdapter
from app.connectors.drive.onedrive import OneDriveAdapter
from app.connectors.models import AuthType, BrokerType, ConnectorDefinition, ConnectorType, TrustLevel

# ── Fixtures ────────────────────────────────────────────────


def _connector(slug: str, broker: BrokerType = BrokerType.IN_HOUSE) -> ConnectorDefinition:
    import uuid as _uuid

    return ConnectorDefinition(
        id=_uuid.uuid4(),
        slug=slug,
        name=slug.title(),
        description=f"{slug} connector",
        icon="Plug",
        category="cloud_storage",
        connector_type=ConnectorType.OAUTH_API,
        auth_type=AuthType.OAUTH2,
        auth_config={},
        trust_level=TrustLevel.VERIFIED,
        broker=broker,
        requires_app_credentials=True,
        is_system=True,
        is_active=True,
        version="1.0.0",
        tags=[],
    )


def _connection():
    import uuid as _uuid

    conn = MagicMock()
    conn.id = _uuid.uuid4()
    conn.tenant_id = _uuid.uuid4()
    return conn


def _make_response(
    *,
    status_code: int = 200,
    json_body: dict | list | None = None,
    content: bytes | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    # Bind a dummy request so ``raise_for_status`` can fire on non-2xx.
    req = httpx.Request("GET", "https://test.local/")
    resp = httpx.Response(
        status_code=status_code,
        json=json_body if content is None else None,
        content=content,
        headers=headers or {},
        request=req,
    )
    return resp


class _MockAsyncClient:
    """Stand-in for ``httpx.AsyncClient`` used as an async context manager.

    Records every ``get``/``post`` call and returns scripted responses in
    order. Adapters treat the instance opaquely, so this covers 100% of
    the HTTP surface without requiring a real respx install.
    """

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _MockAsyncClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def get(self, url: str, **kwargs) -> httpx.Response:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self._responses.pop(0)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self._responses.pop(0)


def _patch_adapter(adapter, *, token: str = "test-token", responses=None):
    """Wire the adapter to skip credential lookup and use a mocked client."""
    mock_client = _MockAsyncClient(responses or [])
    adapter._access_token = AsyncMock(return_value=token)
    adapter._client = lambda **_kw: mock_client
    return mock_client


# ── Dropbox ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dropbox_list_root_returns_items():
    adapter = DropboxDriveAdapter()
    mock = _patch_adapter(
        adapter,
        responses=[
            _make_response(
                json_body={
                    "entries": [
                        {
                            ".tag": "folder",
                            "id": "id:111",
                            "name": "Reports",
                            "path_display": "/Reports",
                            "path_lower": "/reports",
                        },
                        {
                            ".tag": "file",
                            "id": "id:222",
                            "name": "budget.xlsx",
                            "path_display": "/budget.xlsx",
                            "path_lower": "/budget.xlsx",
                            "size": 4096,
                            "server_modified": "2026-04-10T12:00:00Z",
                            "rev": "abc",
                        },
                    ],
                    "has_more": False,
                }
            )
        ],
    )

    listing = await adapter.list(
        connection=_connection(),
        connector_def=_connector("dropbox"),
        db=MagicMock(),
        path="",
    )

    assert isinstance(listing, DriveListing)
    assert listing.cursor is None
    assert [i.name for i in listing.items] == ["Reports", "budget.xlsx"]
    assert listing.items[0].is_folder is True
    assert listing.items[1].size == 4096
    assert listing.items[1].extra == {"rev": "abc"}

    call = mock.calls[0]
    assert call["url"].endswith("/2/files/list_folder")
    assert call["json"]["path"] == ""  # root


@pytest.mark.asyncio
async def test_dropbox_list_uses_cursor_continuation():
    adapter = DropboxDriveAdapter()
    mock = _patch_adapter(
        adapter,
        responses=[_make_response(json_body={"entries": [], "has_more": False})],
    )

    await adapter.list(
        connection=_connection(),
        connector_def=_connector("dropbox"),
        db=MagicMock(),
        path="",
        cursor="opaque-cursor-123",
    )

    call = mock.calls[0]
    assert call["url"].endswith("/2/files/list_folder/continue")
    assert call["json"] == {"cursor": "opaque-cursor-123"}


@pytest.mark.asyncio
async def test_dropbox_download_reads_bytes_from_body():
    adapter = DropboxDriveAdapter()
    payload_bytes = b"%PDF-1.4\n...fake pdf..."
    mock = _patch_adapter(
        adapter,
        responses=[
            _make_response(
                content=payload_bytes,
                headers={
                    "Dropbox-API-Result": json.dumps({"name": "report.pdf", "size": len(payload_bytes)}),
                },
            )
        ],
    )

    file_ = await adapter.download(
        connection=_connection(),
        connector_def=_connector("dropbox"),
        file_id="id:222",
        db=MagicMock(),
    )

    assert isinstance(file_, DriveFile)
    assert file_.content == payload_bytes
    assert file_.filename == "report.pdf"
    assert file_.size == len(payload_bytes)
    assert file_.mime_type == "application/pdf"

    call = mock.calls[0]
    assert call["url"].endswith("/2/files/download")
    assert json.loads(call["headers"]["Dropbox-API-Arg"])["path"] == "id:222"


@pytest.mark.asyncio
async def test_dropbox_download_404_maps_to_not_found():
    adapter = DropboxDriveAdapter()
    _patch_adapter(
        adapter,
        responses=[_make_response(status_code=409, json_body={"error_summary": "not_found"})],
    )

    with pytest.raises(DriveFileNotFoundError):
        await adapter.download(
            connection=_connection(),
            connector_def=_connector("dropbox"),
            file_id="id:bogus",
            db=MagicMock(),
        )


# ── Google Drive ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_google_drive_list_passes_parent_id_in_query():
    adapter = GoogleDriveAdapter()
    mock = _patch_adapter(
        adapter,
        responses=[
            _make_response(
                json_body={
                    "files": [
                        {
                            "id": "gdrive-folder-1",
                            "name": "Plans",
                            "mimeType": "application/vnd.google-apps.folder",
                        },
                        {
                            "id": "gdrive-file-1",
                            "name": "notes.docx",
                            "mimeType": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                            "size": "1024",
                            "modifiedTime": "2026-04-11T09:00:00Z",
                        },
                    ],
                    "nextPageToken": "NEXT",
                }
            )
        ],
    )

    listing = await adapter.list(
        connection=_connection(),
        connector_def=_connector("google-workspace"),
        db=MagicMock(),
        path="parent-abc",
    )

    assert listing.cursor == "NEXT"
    assert listing.items[0].is_folder is True
    assert listing.items[1].size == 1024

    call = mock.calls[0]
    assert call["url"] == "/drive/v3/files"
    assert "'parent-abc' in parents" in call["params"]["q"]
    assert call["params"]["pageSize"] >= 1


@pytest.mark.asyncio
async def test_google_drive_download_uses_alt_media_for_regular_file():
    adapter = GoogleDriveAdapter()
    payload = b"binary-file-contents"
    mock = _patch_adapter(
        adapter,
        responses=[
            _make_response(
                json_body={
                    "id": "gdrive-file-1",
                    "name": "notes.pdf",
                    "mimeType": "application/pdf",
                    "size": str(len(payload)),
                }
            ),
            _make_response(content=payload),
        ],
    )

    file_ = await adapter.download(
        connection=_connection(),
        connector_def=_connector("google-workspace"),
        file_id="gdrive-file-1",
        db=MagicMock(),
    )

    assert file_.content == payload
    assert file_.filename == "notes.pdf"
    assert file_.mime_type == "application/pdf"
    # second call is the content fetch with ?alt=media
    content_call = mock.calls[1]
    assert content_call["url"] == "/drive/v3/files/gdrive-file-1"
    assert content_call["params"]["alt"] == "media"


@pytest.mark.asyncio
async def test_google_drive_download_exports_native_doc_to_docx():
    adapter = GoogleDriveAdapter()
    exported = b"fake-docx-bytes"
    mock = _patch_adapter(
        adapter,
        responses=[
            _make_response(
                json_body={
                    "id": "gdrive-doc-1",
                    "name": "Meeting Notes",
                    "mimeType": "application/vnd.google-apps.document",
                }
            ),
            _make_response(content=exported),
        ],
    )

    file_ = await adapter.download(
        connection=_connection(),
        connector_def=_connector("google-workspace"),
        file_id="gdrive-doc-1",
        db=MagicMock(),
    )

    assert file_.content == exported
    assert file_.filename == "Meeting Notes.docx"
    assert file_.mime_type == ("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    export_call = mock.calls[1]
    assert export_call["url"] == "/drive/v3/files/gdrive-doc-1/export"
    assert export_call["params"]["mimeType"].endswith("wordprocessingml.document")


# ── OneDrive ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_onedrive_list_root_uses_root_children_endpoint():
    adapter = OneDriveAdapter()
    mock = _patch_adapter(
        adapter,
        responses=[
            _make_response(
                json_body={
                    "value": [
                        {
                            "id": "onedrive-folder-1",
                            "name": "Documents",
                            "folder": {"childCount": 5},
                        },
                        {
                            "id": "onedrive-file-1",
                            "name": "design.pdf",
                            "file": {"mimeType": "application/pdf"},
                            "size": 512,
                            "lastModifiedDateTime": "2026-04-12T10:00:00Z",
                        },
                    ],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/...skip=200",
                }
            )
        ],
    )

    listing = await adapter.list(
        connection=_connection(),
        connector_def=_connector("onedrive"),
        db=MagicMock(),
    )

    assert listing.items[0].is_folder is True
    assert listing.items[1].mime_type == "application/pdf"
    assert listing.cursor and listing.cursor.startswith("https://graph.")

    call = mock.calls[0]
    assert call["url"].endswith("/me/drive/root/children")


@pytest.mark.asyncio
async def test_onedrive_download_fetches_metadata_then_content():
    adapter = OneDriveAdapter()
    payload = b"powerpoint-bytes"
    mock = _patch_adapter(
        adapter,
        responses=[
            _make_response(
                json_body={
                    "id": "onedrive-file-1",
                    "name": "slides.pptx",
                    "file": {
                        "mimeType": ("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
                    },
                    "size": len(payload),
                }
            ),
            _make_response(
                content=payload,
                headers={
                    "Content-Type": ("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
                },
            ),
        ],
    )

    file_ = await adapter.download(
        connection=_connection(),
        connector_def=_connector("onedrive"),
        file_id="onedrive-file-1",
        db=MagicMock(),
    )

    assert file_.content == payload
    assert file_.filename == "slides.pptx"
    assert file_.mime_type.endswith("presentationml.presentation")

    meta_call, content_call = mock.calls
    assert meta_call["url"].endswith("/me/drive/items/onedrive-file-1")
    assert content_call["url"].endswith("/me/drive/items/onedrive-file-1/content")


# ── Composio-brokered connections are rejected ─────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_cls,slug",
    [
        (DropboxDriveAdapter, "dropbox"),
        (GoogleDriveAdapter, "google-workspace"),
        (OneDriveAdapter, "onedrive"),
    ],
)
async def test_composio_brokered_connection_rejected(adapter_cls, slug):
    adapter = adapter_cls()
    with pytest.raises(ComposioNotSupportedError):
        await adapter.list(
            connection=_connection(),
            connector_def=_connector(slug, broker=BrokerType.COMPOSIO),
            db=MagicMock(),
        )
    with pytest.raises(ComposioNotSupportedError):
        await adapter.download(
            connection=_connection(),
            connector_def=_connector(slug, broker=BrokerType.COMPOSIO),
            file_id="anything",
            db=MagicMock(),
        )
