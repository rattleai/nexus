"""Tests for MCP tool input validation hardening."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.mcp.errors import McpError
from app.mcp.tools.ai import ai_complete
from app.mcp.tools.jobs import job_create
from app.mcp.tools.team import team_invite


def _make_tenant():
    return MagicMock(id=uuid.uuid4(), name="Test", is_active=True, settings={})


@pytest.mark.asyncio
async def test_ai_complete_empty_messages():
    """Test that empty messages list is rejected."""
    with pytest.raises(McpError, match="cannot be empty"):
        await ai_complete(
            model="gpt-4o", messages=[], tenant=_make_tenant(), db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_ai_complete_too_many_messages():
    """Test that excessive messages are rejected."""
    messages = [{"role": "user", "content": "hi"}] * 201
    with pytest.raises(McpError, match="Too many messages"):
        await ai_complete(
            model="gpt-4o", messages=messages, tenant=_make_tenant(), db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_ai_complete_invalid_message_format():
    """Test that messages without role/content are rejected."""
    with pytest.raises(McpError, match="missing required keys"):
        await ai_complete(
            model="gpt-4o",
            messages=[{"text": "hello"}],
            tenant=_make_tenant(),
            db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_ai_complete_invalid_role():
    """Test that invalid roles are rejected."""
    with pytest.raises(McpError, match="Invalid role"):
        await ai_complete(
            model="gpt-4o",
            messages=[{"role": "admin", "content": "hello"}],
            tenant=_make_tenant(),
            db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_job_create_empty_type():
    """Test that empty job type is rejected."""
    with pytest.raises(McpError, match="cannot be empty"):
        await job_create(
            job_type="", tenant=_make_tenant(), db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_job_create_oversized_payload():
    """Test that oversized payloads are rejected."""
    large_payload = {"data": "x" * 2_000_000}
    with pytest.raises(McpError, match="Payload too large"):
        await job_create(
            job_type="test",
            payload=large_payload,
            tenant=_make_tenant(),
            db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_team_invite_invalid_email():
    """Test that invalid emails are rejected."""
    with pytest.raises(McpError, match="Invalid email"):
        await team_invite(
            email="not-valid", role="member", tenant=_make_tenant(), db=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_team_invite_invalid_role():
    """Test that invalid roles are rejected."""
    with pytest.raises(McpError, match="Invalid role"):
        await team_invite(
            email="test@example.com",
            role="owner",
            tenant=_make_tenant(),
            db=AsyncMock(),
        )
