"""Tests for MCP file tools."""

import base64
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.errors import McpError
from app.mcp.tools.files import file_download, file_list, file_upload


def _make_tenant():
    return MagicMock(id=uuid.uuid4(), name="Test", is_active=True)


@pytest.mark.asyncio
async def test_file_upload_success():
    """Test successful file upload."""
    tenant = _make_tenant()
    mock_db = AsyncMock()
    content = b"hello world"
    content_b64 = base64.b64encode(content).decode()

    mock_storage = MagicMock()
    mock_storage.upload = MagicMock()

    with (
        patch("app.mcp.tools.files._get_storage", return_value=mock_storage),
        patch("app.config.settings", MagicMock(MAX_UPLOAD_SIZE_BYTES=10_485_760)),
    ):
        result = await file_upload(
            filename="test.txt",
            content_base64=content_b64,
            content_type="text/plain",
            tenant=tenant,
            db=mock_db,
        )

    assert result["filename"] == "test.txt"
    assert result["size_bytes"] == len(content)
    assert result["content_type"] == "text/plain"
    assert result["key"].startswith(f"tenants/{tenant.id}/")
    mock_storage.upload.assert_called_once()


@pytest.mark.asyncio
async def test_file_upload_invalid_base64():
    """Test that invalid base64 raises an error."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    with pytest.raises(McpError, match="Invalid base64"):
        await file_upload(
            filename="test.txt",
            content_base64="not-valid-base64!!!",
            tenant=tenant,
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_file_upload_too_large():
    """Test that oversized files are rejected."""
    tenant = _make_tenant()
    mock_db = AsyncMock()
    content = b"x" * 100
    content_b64 = base64.b64encode(content).decode()

    with (
        patch("app.config.settings", MagicMock(MAX_UPLOAD_SIZE_BYTES=50)),
        pytest.raises(McpError, match="exceeds maximum"),
    ):
        await file_upload(
            filename="big.bin",
            content_base64=content_b64,
            tenant=tenant,
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_file_upload_sanitizes_filename():
    """Test that dangerous filenames are sanitized."""
    tenant = _make_tenant()
    mock_db = AsyncMock()
    content_b64 = base64.b64encode(b"data").decode()

    mock_storage = MagicMock()

    with (
        patch("app.mcp.tools.files._get_storage", return_value=mock_storage),
        patch("app.config.settings", MagicMock(MAX_UPLOAD_SIZE_BYTES=10_485_760)),
    ):
        result = await file_upload(
            filename="../../.env",
            content_base64=content_b64,
            tenant=tenant,
            db=mock_db,
        )

    # Leading dots should be stripped, path traversal neutralized
    assert not result["filename"].startswith(".")


@pytest.mark.asyncio
async def test_file_download_success():
    """Test successful file download."""
    tenant = _make_tenant()
    mock_db = AsyncMock()
    content = b"file content"

    mock_storage = MagicMock()
    mock_storage.download = MagicMock(return_value=content)

    file_key = f"tenants/{tenant.id}/abc123_test.txt"

    with patch("app.mcp.tools.files._get_storage", return_value=mock_storage):
        result = await file_download(file_key=file_key, tenant=tenant, db=mock_db)

    assert result["content_base64"] == base64.b64encode(content).decode()
    assert result["size_bytes"] == len(content)


@pytest.mark.asyncio
async def test_file_download_wrong_tenant():
    """Test that accessing another tenant's file is denied."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    other_tenant_id = uuid.uuid4()
    file_key = f"tenants/{other_tenant_id}/secret.txt"

    with pytest.raises(McpError, match="Access denied"):
        await file_download(file_key=file_key, tenant=tenant, db=mock_db)


@pytest.mark.asyncio
async def test_file_list():
    """Test listing files."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_storage = MagicMock()
    mock_storage.list_objects = MagicMock(
        return_value=[
            f"tenants/{tenant.id}/abc_file1.txt",
            f"tenants/{tenant.id}/def_file2.csv",
        ]
    )

    with patch("app.mcp.tools.files._get_storage", return_value=mock_storage):
        result = await file_list(tenant=tenant, db=mock_db)

    assert len(result) == 2
    assert result[0]["filename"] == "abc_file1.txt"
