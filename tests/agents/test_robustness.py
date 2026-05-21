"""Resilience and robustness tests for the agent subsystem.

Verifies fail-closed behaviour when Redis is unavailable, best-effort
spending tracking, and circuit-breaker integration for external tool calls.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.governance import GovernanceEngine, GovernanceViolationError
from app.agents.memory import AgentMemoryManager
from app.agents.models import TenantTool
from app.agents.tool_registry import ToolRegistry

# ── Governance: Redis unavailable → fail-closed (spending) ────────────


@pytest.mark.asyncio
async def test_governance_spend_limit_fails_closed_when_redis_unavailable():
    """When max_spend_per_day_usd is set and Redis is down, the engine must
    raise GovernanceViolationError (fail-closed) rather than silently allowing
    the action."""
    engine = GovernanceEngine({"max_spend_per_day_usd": 10.0})

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    mock_redis.eval = AsyncMock(side_effect=ConnectionError("Redis unavailable"))

    with (
        patch("app.agents.governance.redis_pool", mock_redis),
        patch("app.agents.governance.emit", new_callable=AsyncMock),
        pytest.raises(GovernanceViolationError) as exc_info,
    ):
        await engine.check(
            action="tool_call",
            context={
                "instance_id": "inst-1",
                "agent_id": "agent-1",
                "current_cost": 0.0,
            },
            tenant_id=uuid.uuid4(),
        )

    assert exc_info.value.violation_type == "spending_limit"
    assert "redis_unavailable" in exc_info.value.details.get("reason", "")


# ── Governance: Redis unavailable → fail-closed (rate limit) ──────────


@pytest.mark.asyncio
async def test_governance_rate_limit_fails_closed_when_redis_unavailable():
    """When max_requests_per_minute is set and Redis is down, the engine
    must raise GovernanceViolationError (fail-closed)."""
    engine = GovernanceEngine({"max_requests_per_minute": 5})

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(side_effect=ConnectionError("Redis unavailable"))

    with (
        patch("app.agents.governance.redis_pool", mock_redis),
        patch("app.agents.governance.emit", new_callable=AsyncMock),
        pytest.raises(GovernanceViolationError) as exc_info,
    ):
        await engine.check(
            action="tool_call",
            context={
                "instance_id": "inst-1",
                "agent_id": "agent-1",
            },
            tenant_id=uuid.uuid4(),
        )

    assert exc_info.value.violation_type == "rate_limit"
    assert "redis_unavailable" in exc_info.value.details.get("reason", "")


# ── Governance: track_spending is best-effort ─────────────────────────


@pytest.mark.asyncio
async def test_track_spending_does_not_propagate_redis_errors():
    """track_spending() is best-effort: if Redis raises, the exception
    is logged but NOT propagated to the caller."""
    mock_redis = AsyncMock()
    mock_redis.incrbyfloat = AsyncMock(
        side_effect=ConnectionError("Redis unavailable"),
    )

    with (
        patch("app.agents.governance.redis_pool", mock_redis),
        patch("app.agents.governance.emit", new_callable=AsyncMock),
    ):
        # Should complete without raising
        await GovernanceEngine.track_spending(
            tenant_id=uuid.uuid4(),
            agent_id="agent1",
            instance_id="inst1",
            cost_usd=0.5,
        )


# ── Memory manager: short-term Redis failure propagates ───────────────


@pytest.mark.asyncio
async def test_memory_set_short_term_propagates_redis_error():
    """set_short_term() relies on Redis; if redis_pool.eval raises,
    the error must propagate (it is NOT silently swallowed)."""
    mock_db = AsyncMock()
    manager = AgentMemoryManager(mock_db)

    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(
        side_effect=ConnectionError("Redis unavailable"),
    )

    with patch("app.agents.memory.redis_pool", mock_redis), pytest.raises(ConnectionError):
        await manager.set_short_term(
            instance_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            key="test_key",
            value={"data": 1},
        )


# ── Tool registry: external tool circuit breaker on failure ───────────


@pytest.mark.asyncio
async def test_tool_registry_external_records_failure_and_returns_error():
    """When an external tool HTTP call fails, _invoke_external must:
    1. Record a failure on the circuit breaker.
    2. Return an error dict (NOT raise an exception)."""
    registry = ToolRegistry()

    tenant_id = uuid.uuid4()

    tool = MagicMock(spec=TenantTool)
    tool.endpoint_url = "https://example.com/tool"
    tool.tool_name = "my_tool"
    tool.tenant_id = tenant_id
    tool.auth_config = {}

    mock_breaker = MagicMock()
    mock_breaker.is_open.return_value = False

    with (
        patch("app.agents.tool_registry._tool_breaker", mock_breaker),
        patch("app.core.url_validation.validate_url"),
        patch("httpx.AsyncClient") as mock_client_cls,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await registry._invoke_external(tool, {"arg": "value"})

    # Must return an error dict, not raise
    assert isinstance(result, dict)
    assert "error" in result

    # Circuit breaker must have recorded the failure
    mock_breaker.record_failure.assert_called_once()
