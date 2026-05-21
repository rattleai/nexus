"""Tests for MCP authentication."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.auth import MCPAuthError, authenticate_api_key, check_scopes


def _make_api_key(tenant, scopes=None):
    key = MagicMock(
        tenant=tenant,
        scopes=scopes or ["ai:read", "ai:write", "jobs:read"],
        active=True,
    )
    return key


def _make_tenant():
    return MagicMock(
        id=uuid.uuid4(),
        name="Test Tenant",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_authenticate_valid_key():
    tenant = _make_tenant()
    api_key = _make_api_key(tenant)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = api_key
    mock_db.execute = AsyncMock(return_value=mock_result)

    with patch("app.mcp.auth.hash_api_key", return_value="hashed"):
        result_key, result_tenant = await authenticate_api_key("raw-key", mock_db)

    assert result_key is api_key
    assert result_tenant is tenant


@pytest.mark.asyncio
async def test_authenticate_invalid_key():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.mcp.auth.hash_api_key", return_value="hashed"),
        pytest.raises(MCPAuthError, match="Invalid API key"),
    ):
        await authenticate_api_key("bad-key", mock_db)


@pytest.mark.asyncio
async def test_authenticate_inactive_tenant():
    tenant = _make_tenant()
    tenant.is_active = False
    api_key = _make_api_key(tenant)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = api_key
    mock_db.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.mcp.auth.hash_api_key", return_value="hashed"),
        pytest.raises(MCPAuthError, match="Tenant not found or inactive"),
    ):
        await authenticate_api_key("raw-key", mock_db)


def test_check_scopes_granted():
    api_key = MagicMock(scopes=["ai:read", "ai:write", "jobs:read"])
    # Should not raise
    check_scopes(api_key, "ai:read")
    check_scopes(api_key, "ai:read", "ai:write")


def test_check_scopes_missing():
    from app.mcp.errors import McpError

    api_key = MagicMock(scopes=["ai:read"])
    with pytest.raises(McpError, match="Insufficient API key scopes"):
        check_scopes(api_key, "ai:write")


def test_check_scopes_empty():
    from app.mcp.errors import McpError

    api_key = MagicMock(scopes=[])
    with pytest.raises(McpError, match="Insufficient API key scopes"):
        check_scopes(api_key, "ai:read")
