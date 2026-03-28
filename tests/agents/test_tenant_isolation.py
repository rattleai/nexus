"""Tests for tenant isolation across the agent layer.

Verifies that:
    - AgentDatabaseGateway._verify_tenant_context blocks mismatched / missing tenant context
    - _verify_tenant_context fails closed on DB/Redis errors
    - API-level helpers (_verify_instance_ownership, _get_agent_or_404) reject cross-tenant access
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.agents.db_gateway import AgentDatabaseGateway, GatewayViolationError, QueryPolicy

# ── Helpers ────────────────────────────────────────────────────────────


def _make_gateway(tenant_id: uuid.UUID | None = None, **kwargs) -> AgentDatabaseGateway:
    return AgentDatabaseGateway(
        tenant_id=tenant_id or uuid.uuid4(),
        agent_id="test-agent",
        instance_id="test-instance",
        policy=QueryPolicy(require_where_clause=False),
        **kwargs,
    )


def _mock_db_returning(scalar_value):
    """Create an AsyncMock db session whose execute returns the given scalar."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    db.execute = AsyncMock(return_value=result)
    return db


# ── TestVerifyTenantContextMissing ─────────────────────────────────────


class TestVerifyTenantContextMissing:
    """app.tenant_id not set -> GatewayViolationError(tenant_context_missing)."""

    @pytest.mark.asyncio
    async def test_blocks_when_tenant_id_not_set(self):
        """When current_setting('app.tenant_id') returns None, query is blocked."""
        gw = _make_gateway()
        db = _mock_db_returning(None)

        with pytest.raises(GatewayViolationError) as exc_info:
            await gw._verify_tenant_context(db)

        assert exc_info.value.violation_type == "tenant_context_missing"

    @pytest.mark.asyncio
    async def test_blocks_when_tenant_id_returns_empty_string(self):
        """Empty string from current_setting is treated as missing."""
        gw = _make_gateway()
        db = _mock_db_returning("")

        with pytest.raises(GatewayViolationError) as exc_info:
            await gw._verify_tenant_context(db)

        assert exc_info.value.violation_type == "tenant_context_missing"


# ── TestVerifyTenantContextMismatch ────────────────────────────────────


class TestVerifyTenantContextMismatch:
    """app.tenant_id set to a DIFFERENT tenant -> GatewayViolationError(tenant_context_mismatch)."""

    @pytest.mark.asyncio
    async def test_blocks_when_tenant_ids_differ(self):
        """Gateway tenant_id and DB session tenant_id mismatch raises violation."""
        gateway_tenant = uuid.uuid4()
        db_tenant = uuid.uuid4()
        gw = _make_gateway(tenant_id=gateway_tenant)
        db = _mock_db_returning(str(db_tenant))

        with pytest.raises(GatewayViolationError) as exc_info:
            await gw._verify_tenant_context(db)

        assert exc_info.value.violation_type == "tenant_context_mismatch"


# ── TestVerifyTenantContextMatch ───────────────────────────────────────


class TestVerifyTenantContextMatch:
    """app.tenant_id matches gateway's tenant_id -> no error."""

    @pytest.mark.asyncio
    async def test_allows_when_tenant_ids_match(self):
        """No exception when the DB session tenant matches the gateway tenant."""
        tenant_id = uuid.uuid4()
        gw = _make_gateway(tenant_id=tenant_id)
        db = _mock_db_returning(str(tenant_id))

        # Should not raise
        await gw._verify_tenant_context(db)


# ── TestVerifyTenantContextFailClosed ──────────────────────────────────


class TestVerifyTenantContextFailClosed:
    """DB check fails (connection error, etc.) -> fail-closed with GatewayViolationError."""

    @pytest.mark.asyncio
    async def test_blocks_on_db_execute_error(self):
        """If db.execute raises an unexpected exception, query is blocked (fail-closed)."""
        gw = _make_gateway()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=RuntimeError("connection lost"))

        with pytest.raises(GatewayViolationError) as exc_info:
            await gw._verify_tenant_context(db)

        assert exc_info.value.violation_type == "tenant_context_unavailable"

    @pytest.mark.asyncio
    async def test_blocks_on_scalar_extraction_error(self):
        """If scalar_one_or_none raises, query is blocked (fail-closed)."""
        gw = _make_gateway()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.side_effect = Exception("unexpected multiple rows")
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(GatewayViolationError) as exc_info:
            await gw._verify_tenant_context(db)

        assert exc_info.value.violation_type == "tenant_context_unavailable"


# ── TestVerifyInstanceOwnership ────────────────────────────────────────


class TestVerifyInstanceOwnership:
    """_verify_instance_ownership from the agents API module."""

    @pytest.mark.asyncio
    async def test_rejects_cross_tenant_instance(self):
        """Instance with a different tenant_id triggers 404."""
        from app.api.v1.agents import _verify_instance_ownership

        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        instance_id = uuid.uuid4()

        # Simulate db.get returning an instance owned by tenant_b
        mock_instance = MagicMock()
        mock_instance.tenant_id = tenant_b

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_instance)

        with pytest.raises(HTTPException) as exc_info:
            await _verify_instance_ownership(db, instance_id, tenant_a)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_instance(self):
        """Instance not found (db.get returns None) triggers 404."""
        from app.api.v1.agents import _verify_instance_ownership

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await _verify_instance_ownership(db, uuid.uuid4(), uuid.uuid4())

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_allows_same_tenant_instance(self):
        """Instance owned by the requesting tenant passes without error."""
        from app.api.v1.agents import _verify_instance_ownership

        tenant_id = uuid.uuid4()
        instance_id = uuid.uuid4()

        mock_instance = MagicMock()
        mock_instance.tenant_id = tenant_id

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_instance)

        # Should not raise
        await _verify_instance_ownership(db, instance_id, tenant_id)


# ── TestGetAgentOr404 ──────────────────────────────────────────────────


class TestGetAgentOr404:
    """_get_agent_or_404 from the agents API module."""

    @pytest.mark.asyncio
    async def test_rejects_cross_tenant_agent(self):
        """Agent owned by a different tenant triggers 404."""
        from app.api.v1.agents import _get_agent_or_404

        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()

        mock_agent = MagicMock()
        mock_agent.tenant_id = tenant_b
        mock_agent.deleted_at = None

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_agent)

        with pytest.raises(HTTPException) as exc_info:
            await _get_agent_or_404(db, uuid.uuid4(), tenant_a)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_deleted_agent(self):
        """Soft-deleted agent (deleted_at is set) triggers 404."""
        from app.api.v1.agents import _get_agent_or_404
        from datetime import datetime, UTC

        tenant_id = uuid.uuid4()
        mock_agent = MagicMock()
        mock_agent.tenant_id = tenant_id
        mock_agent.deleted_at = datetime.now(UTC)

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_agent)

        with pytest.raises(HTTPException) as exc_info:
            await _get_agent_or_404(db, uuid.uuid4(), tenant_id)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_agent(self):
        """Agent not found (db.get returns None) triggers 404."""
        from app.api.v1.agents import _get_agent_or_404

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await _get_agent_or_404(db, uuid.uuid4(), uuid.uuid4())

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_allows_valid_agent(self):
        """Active agent owned by the requesting tenant is returned."""
        from app.api.v1.agents import _get_agent_or_404

        tenant_id = uuid.uuid4()
        agent_id = uuid.uuid4()

        mock_agent = MagicMock()
        mock_agent.tenant_id = tenant_id
        mock_agent.deleted_at = None

        db = AsyncMock()
        db.get = AsyncMock(return_value=mock_agent)

        result = await _get_agent_or_404(db, agent_id, tenant_id)
        assert result is mock_agent
