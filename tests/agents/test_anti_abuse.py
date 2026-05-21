"""Tests for anti-abuse features in the governance engine.

Covers:
    - Abuse pattern detection with escalating actions
    - Tenant circuit breaker (trip, check, Redis failure safety)
    - Progressive throttling with exponential backoff
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.governance import GovernanceEngine

# ── TestAbusePatterns ─────────────────────────────────────────────────


class TestAbusePatterns:
    """Abuse pattern detection based on violation counts and abuse scores."""

    @pytest.mark.asyncio
    async def test_low_violations_no_action(self):
        engine = GovernanceEngine(policy={})
        with patch("app.agents.governance.redis_pool") as mock_redis:
            pipe = MagicMock()  # pipeline methods (get) are sync queue calls
            pipe.execute = AsyncMock(return_value=[b"2", b"1"])
            mock_redis.pipeline = MagicMock(return_value=pipe)

            result = await engine.check_abuse_patterns(
                tenant_id=uuid.uuid4(),
                agent_id="agent-1",
                instance_id="inst-1",
            )
        assert result["action"] == "none"
        assert result["violation_count"] == 2

    @pytest.mark.asyncio
    async def test_medium_violations_throttle(self):
        engine = GovernanceEngine(policy={})
        with patch("app.agents.governance.redis_pool") as mock_redis:
            pipe = MagicMock()
            pipe.execute = AsyncMock(return_value=[b"5", b"0"])
            mock_redis.pipeline = MagicMock(return_value=pipe)

            result = await engine.check_abuse_patterns(
                tenant_id=uuid.uuid4(),
                agent_id="agent-1",
                instance_id="inst-1",
            )
        assert result["action"] == "throttle"

    @pytest.mark.asyncio
    async def test_high_violations_suspend(self):
        engine = GovernanceEngine(policy={})
        with patch("app.agents.governance.redis_pool") as mock_redis:
            pipe = MagicMock()
            pipe.execute = AsyncMock(return_value=[b"10", b"0"])
            mock_redis.pipeline = MagicMock(return_value=pipe)

            result = await engine.check_abuse_patterns(
                tenant_id=uuid.uuid4(),
                agent_id="agent-1",
                instance_id="inst-1",
            )
        assert result["action"] == "suspend"


# ── TestTenantCircuitBreaker ──────────────────────────────────────────


class TestTenantCircuitBreaker:
    """Tenant-level circuit breaker for pausing all agent execution."""

    @pytest.mark.asyncio
    async def test_not_open_by_default(self):
        with patch("app.agents.governance.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            is_open, reason = await GovernanceEngine.check_tenant_circuit_breaker(
                uuid.uuid4(),
            )
        assert is_open is False
        assert reason == ""

    @pytest.mark.asyncio
    async def test_tripped_blocks_execution(self):
        cb_data = json.dumps({"reason": "Too many violations"})
        with patch("app.agents.governance.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value=cb_data)
            is_open, reason = await GovernanceEngine.check_tenant_circuit_breaker(
                uuid.uuid4(),
            )
        assert is_open is True
        assert reason == "Too many violations"

    @pytest.mark.asyncio
    async def test_trip_sets_key_with_ttl(self):
        tenant_id = uuid.uuid4()
        with patch("app.agents.governance.redis_pool") as mock_redis:
            mock_redis.setex = AsyncMock()
            await GovernanceEngine.trip_tenant_circuit_breaker(
                tenant_id,
                reason="abuse detected",
                duration_seconds=600,
            )
        mock_redis.setex.assert_awaited_once()
        args = mock_redis.setex.call_args
        # setex(key, ttl, value)
        assert args[0][1] == 600
        stored = json.loads(args[0][2])
        assert stored["reason"] == "abuse detected"

    @pytest.mark.asyncio
    async def test_redis_failure_returns_safe(self):
        with patch("app.agents.governance.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
            is_open, reason = await GovernanceEngine.check_tenant_circuit_breaker(
                uuid.uuid4(),
            )
        # Fail-open: if Redis is down, do NOT block execution
        assert is_open is False
        assert reason == ""


# ── TestProgressiveThrottling ─────────────────────────────────────────


class TestProgressiveThrottling:
    """Progressive throttling with exponential backoff delays."""

    @pytest.mark.asyncio
    async def test_no_throttle_initially(self):
        with patch("app.agents.governance.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            delay = await GovernanceEngine.apply_progressive_throttling(
                tenant_id=uuid.uuid4(),
                agent_id="agent-1",
                instance_id="inst-1",
            )
        assert delay == 0.0

    @pytest.mark.asyncio
    async def test_escalating_delays(self):
        with patch("app.agents.governance.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value="3")
            delay = await GovernanceEngine.apply_progressive_throttling(
                tenant_id=uuid.uuid4(),
                agent_id="agent-1",
                instance_id="inst-1",
            )
        # 2^(3-1) = 4, min(4, 30) = 4.0
        assert delay == 4.0

    @pytest.mark.asyncio
    async def test_max_cap(self):
        with patch("app.agents.governance.redis_pool") as mock_redis:
            mock_redis.get = AsyncMock(return_value="10")
            delay = await GovernanceEngine.apply_progressive_throttling(
                tenant_id=uuid.uuid4(),
                agent_id="agent-1",
                instance_id="inst-1",
            )
        # 2^(10-1) = 512, min(512, 30) = 30.0
        assert delay == 30.0
