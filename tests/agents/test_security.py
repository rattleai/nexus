"""Tests for tenant isolation and security guarantees in the agent subsystem."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.executor import AgentExecutionError, AgentExecutor
from app.agents.schemas import TenantToolResponse


# ── Tenant isolation: _load_definition ────────────────────────────────


@pytest.mark.asyncio
async def test_load_definition_wrong_tenant_returns_none():
    """_load_definition returns None when the tenant_id does not match any row."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    executor = AgentExecutor(mock_db)
    definition = await executor._load_definition(
        definition_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )

    assert definition is None
    mock_db.execute.assert_awaited_once()


# ── Tenant isolation: _get_or_create_session ──────────────────────────


@pytest.mark.asyncio
async def test_get_or_create_session_wrong_tenant_creates_new_session():
    """When a session_id is provided but the DB query filtered by the wrong
    tenant_id finds nothing, a brand-new session is returned instead of
    leaking another tenant's session."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # no matching session
    mock_db.execute = AsyncMock(return_value=mock_result)

    executor = AgentExecutor(mock_db)

    tenant_id = uuid.uuid4()
    instance = MagicMock()
    instance.id = uuid.uuid4()

    session = await executor._get_or_create_session(
        instance=instance,
        tenant_id=tenant_id,
        session_id=uuid.uuid4(),  # belongs to a different tenant
    )

    # A fresh session should be returned with the correct tenant_id
    assert session.tenant_id == tenant_id
    assert session.messages == []


# ── Tenant isolation: stop ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_wrong_tenant_raises_execution_error():
    """stop() must raise AgentExecutionError when the instance does not belong
    to the given tenant."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # tenant filter excludes it
    mock_db.execute = AsyncMock(return_value=mock_result)

    executor = AgentExecutor(mock_db)

    with patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock):
        with pytest.raises(AgentExecutionError, match="not found"):
            await executor.stop(
                instance_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                reason="test",
            )


# ── Auth config masking ──────────────────────────────────────────────


class TestTenantToolResponseAuthMasking:
    """TenantToolResponse must mask sensitive auth_config fields in responses."""

    def _build_response(self, auth_config: dict) -> TenantToolResponse:
        return TenantToolResponse(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            tool_name="test",
            description="",
            source="tenant",
            input_schema={},
            output_schema={},
            endpoint_url=None,
            auth_config=auth_config,
            is_active=True,
            health_check_url=None,
            metadata={},
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    def test_token_is_masked(self):
        """A bearer token value must be replaced with '***'."""
        response = self._build_response(
            {"type": "bearer", "token": "secret-token-value"},
        )
        assert response.auth_config["token"] == "***"

    def test_key_is_masked(self):
        """An API key value must be replaced with '***'."""
        response = self._build_response(
            {"type": "api_key", "key": "sk-real-api-key-12345"},
        )
        assert response.auth_config["key"] == "***"

    def test_type_field_is_preserved(self):
        """The auth_config type field must pass through without modification."""
        response = self._build_response(
            {"type": "bearer", "token": "secret-token-value"},
        )
        assert response.auth_config["type"] == "bearer"

    def test_empty_auth_config_returns_empty_dict(self):
        """An empty or None auth_config should produce an empty dict."""
        response = self._build_response({})
        assert response.auth_config == {}
