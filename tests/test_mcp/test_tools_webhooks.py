"""Tests for MCP webhook tools."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.errors import McpError
from app.mcp.tools.webhooks import webhook_create, webhook_delete, webhook_list


def _make_tenant():
    return MagicMock(id=uuid.uuid4(), name="Test", is_active=True)


@pytest.mark.asyncio
async def test_webhook_list():
    """Test listing webhooks."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_endpoint = MagicMock(
        id=uuid.uuid4(),
        url="https://example.com/hook",
        events=["job.completed"],
        active=True,
        description="Test hook",
        created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00"),
    )

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_endpoint]
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await webhook_list(tenant=tenant, db=mock_db)

    assert len(result) == 1
    assert result[0]["url"] == "https://example.com/hook"
    assert result[0]["active"] is True


@pytest.mark.asyncio
async def test_webhook_create_success():
    """Test creating a webhook."""
    tenant = _make_tenant()
    mock_db = AsyncMock()
    mock_db.refresh = AsyncMock()

    with (
        patch("app.core.url_validation.validate_webhook_url_async", new_callable=AsyncMock, return_value=None),
        patch("app.core.encryption.encrypt", return_value="encrypted_secret"),
    ):
        result = await webhook_create(
            url="https://example.com/hook",
            events=["job.completed"],
            description="Test",
            tenant=tenant,
            db=mock_db,
        )

    assert result["url"] == "https://example.com/hook"
    assert result["events"] == ["job.completed"]
    assert result["active"] is True
    assert result["signing_secret"].startswith("whsec_")
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_webhook_create_http_rejected():
    """Test that non-HTTPS URLs are rejected."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    with pytest.raises(McpError, match="HTTPS"):
        await webhook_create(
            url="http://insecure.example.com/hook",
            events=["job.completed"],
            tenant=tenant,
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_webhook_create_invalid_event():
    """Test that invalid events are rejected."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    with (
        patch("app.core.url_validation.validate_webhook_url_async", new_callable=AsyncMock, return_value=None),
        pytest.raises(McpError, match="Invalid events"),
    ):
        await webhook_create(
            url="https://example.com/hook",
            events=["nonexistent.event"],
            tenant=tenant,
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_webhook_create_empty_events():
    """Test that empty events list is rejected."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    with (
        patch("app.core.url_validation.validate_webhook_url_async", new_callable=AsyncMock, return_value=None),
        pytest.raises(McpError, match="At least one event"),
    ):
        await webhook_create(
            url="https://example.com/hook",
            events=[],
            tenant=tenant,
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_webhook_delete_success():
    """Test deleting a webhook."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    webhook_id = uuid.uuid4()
    mock_endpoint = MagicMock(id=webhook_id)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_endpoint
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await webhook_delete(
        webhook_id=str(webhook_id), tenant=tenant, db=mock_db,
    )

    assert result["deleted"] is True
    mock_db.delete.assert_called_once_with(mock_endpoint)


@pytest.mark.asyncio
async def test_webhook_delete_not_found():
    """Test deleting a non-existent webhook."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(McpError, match="not found"):
        await webhook_delete(
            webhook_id=str(uuid.uuid4()), tenant=tenant, db=mock_db,
        )


@pytest.mark.asyncio
async def test_webhook_delete_invalid_id():
    """Test deleting with invalid UUID."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    with pytest.raises(McpError, match="Invalid webhook ID"):
        await webhook_delete(webhook_id="not-a-uuid", tenant=tenant, db=mock_db)
