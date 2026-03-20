"""Tests for MCP team tools."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mcp.errors import McpError
from app.mcp.tools.team import team_invite, team_list_members


def _make_tenant():
    return MagicMock(id=uuid.uuid4(), name="Test", is_active=True)


@pytest.mark.asyncio
async def test_team_list_members():
    """Test listing team members."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_member = MagicMock(
        user_id=uuid.uuid4(),
        role=MagicMock(value="admin"),
        user=MagicMock(email="alice@example.com", display_name="Alice"),
        created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00"),
    )

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_member]
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await team_list_members(tenant=tenant, db=mock_db)

    assert len(result) == 1
    assert result[0]["email"] == "a***e@example.com"  # PII masked
    assert result[0]["role"] == "admin"


@pytest.mark.asyncio
async def test_team_invite_success():
    """Test successful team invitation."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    # No existing invitation
    mock_existing_result = MagicMock()
    mock_existing_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_existing_result)
    mock_db.refresh = AsyncMock(return_value=None)

    result = await team_invite(
        email="bob@example.com",
        role="member",
        tenant=tenant,
        db=mock_db,
    )

    assert result["email"] == "bob@example.com"
    assert result["role"] == "member"
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_team_invite_invalid_email():
    """Test that invalid email is rejected."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    with pytest.raises(McpError, match="Invalid email"):
        await team_invite(email="not-an-email", role="member", tenant=tenant, db=mock_db)


@pytest.mark.asyncio
async def test_team_invite_invalid_role():
    """Test that invalid role is rejected."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    with pytest.raises(McpError, match="Invalid role"):
        await team_invite(
            email="valid@example.com",
            role="superadmin",
            tenant=tenant,
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_team_invite_duplicate():
    """Test that duplicate invitations are rejected."""
    tenant = _make_tenant()
    mock_db = AsyncMock()

    # Existing invitation found
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(McpError, match="pending invitation already exists"):
        await team_invite(
            email="bob@example.com",
            role="member",
            tenant=tenant,
            db=mock_db,
        )
