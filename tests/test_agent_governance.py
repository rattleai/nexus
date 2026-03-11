"""Tests for the agent governance engine."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.governance import GovernanceEngine, GovernanceViolation


@pytest.fixture
def strict_policy():
    return {
        "allowed_tools": ["ai_complete", "file_list"],
        "denied_tools": ["webhook_create"],
        "max_spend_per_run_usd": 1.00,
        "max_requests_per_minute": 10,
        "require_approval_for": ["team_invite"],
        "approval_default_action": "deny",
    }


class TestToolAccessControl:
    @pytest.mark.asyncio
    async def test_allowed_tool_passes(self, strict_policy):
        engine = GovernanceEngine(strict_policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            # Should not raise
            await engine.check(
                action="tool_call",
                context={"tool_name": "ai_complete", "instance_id": "x"},
                tenant_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_denied_tool_raises(self, strict_policy):
        engine = GovernanceEngine(strict_policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with pytest.raises(GovernanceViolation) as exc_info:
                await engine.check(
                    action="tool_call",
                    context={"tool_name": "webhook_create", "instance_id": "x"},
                    tenant_id=uuid.uuid4(),
                )
            assert exc_info.value.violation_type == "denied_tool"

    @pytest.mark.asyncio
    async def test_unlisted_tool_raises(self, strict_policy):
        engine = GovernanceEngine(strict_policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with pytest.raises(GovernanceViolation) as exc_info:
                await engine.check(
                    action="tool_call",
                    context={"tool_name": "job_create", "instance_id": "x"},
                    tenant_id=uuid.uuid4(),
                )
            assert exc_info.value.violation_type == "denied_tool"

    @pytest.mark.asyncio
    async def test_non_tool_action_passes(self, strict_policy):
        engine = GovernanceEngine(strict_policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.incr = AsyncMock(return_value=1)
                mock_redis.expire = AsyncMock()
                # Non-tool actions should pass tool check
                await engine.check(
                    action="llm_call",
                    context={"instance_id": "x"},
                    tenant_id=uuid.uuid4(),
                )


class TestSpendingLimits:
    @pytest.mark.asyncio
    async def test_within_budget_passes(self, strict_policy):
        engine = GovernanceEngine(strict_policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.incr = AsyncMock(return_value=1)
                mock_redis.expire = AsyncMock()
                await engine.check(
                    action="llm_call",
                    context={"current_cost": 0.50, "instance_id": "x"},
                    tenant_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_over_budget_raises(self, strict_policy):
        engine = GovernanceEngine(strict_policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with pytest.raises(GovernanceViolation) as exc_info:
                await engine.check(
                    action="llm_call",
                    context={"current_cost": 1.50, "instance_id": "x"},
                    tenant_id=uuid.uuid4(),
                )
            assert exc_info.value.violation_type == "spending_limit"


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_within_rate_limit_passes(self, strict_policy):
        engine = GovernanceEngine(strict_policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.incr = AsyncMock(return_value=5)
                mock_redis.expire = AsyncMock()
                await engine.check(
                    action="llm_call",
                    context={"instance_id": "x"},
                    tenant_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_over_rate_limit_raises(self, strict_policy):
        engine = GovernanceEngine(strict_policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.incr = AsyncMock(return_value=11)
                mock_redis.expire = AsyncMock()
                with pytest.raises(GovernanceViolation) as exc_info:
                    await engine.check(
                        action="llm_call",
                        context={"instance_id": "x"},
                        tenant_id=uuid.uuid4(),
                    )
                assert exc_info.value.violation_type == "rate_limit"


class TestApprovalWorkflow:
    @pytest.mark.asyncio
    async def test_approval_required_raises(self, strict_policy):
        engine = GovernanceEngine(strict_policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with pytest.raises(GovernanceViolation) as exc_info:
                await engine.check(
                    action="tool_call",
                    context={"tool_name": "team_invite", "instance_id": "x"},
                    tenant_id=uuid.uuid4(),
                )
            assert exc_info.value.violation_type == "approval_required"

    @pytest.mark.asyncio
    async def test_no_approval_policy_passes(self):
        engine = GovernanceEngine({"require_approval_for": []})
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.incr = AsyncMock(return_value=1)
                mock_redis.expire = AsyncMock()
                await engine.check(
                    action="tool_call",
                    context={"tool_name": "team_invite", "instance_id": "x"},
                    tenant_id=uuid.uuid4(),
                )


class TestDailySpendingLimits:
    @pytest.mark.asyncio
    async def test_daily_within_budget_passes(self):
        policy = {"max_spend_per_day_usd": 10.0}
        engine = GovernanceEngine(policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.get = AsyncMock(return_value="5.0")  # $5 spent
                mock_redis.incr = AsyncMock(return_value=1)
                mock_redis.expire = AsyncMock()
                await engine.check(
                    action="tool_call",
                    context={"tool_name": "test", "instance_id": "x", "current_cost": 0.5},
                    tenant_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_daily_over_budget_raises(self):
        policy = {"max_spend_per_day_usd": 10.0}
        engine = GovernanceEngine(policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.get = AsyncMock(return_value="10.5")  # Over $10 limit
                mock_redis.incr = AsyncMock(return_value=1)
                mock_redis.expire = AsyncMock()
                with pytest.raises(GovernanceViolation) as exc_info:
                    await engine.check(
                        action="tool_call",
                        context={"tool_name": "test", "instance_id": "x", "current_cost": 0.5},
                        tenant_id=uuid.uuid4(),
                    )
                assert exc_info.value.violation_type == "spending_limit"

    @pytest.mark.asyncio
    async def test_redis_failure_blocks_spending_check(self):
        """When Redis is unavailable and a daily limit is configured, fail-closed."""
        policy = {"max_spend_per_day_usd": 10.0}
        engine = GovernanceEngine(policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
                mock_redis.incr = AsyncMock(return_value=1)
                mock_redis.expire = AsyncMock()
                with pytest.raises(GovernanceViolation) as exc_info:
                    await engine.check(
                        action="tool_call",
                        context={"tool_name": "test", "instance_id": "x", "current_cost": 0.5},
                        tenant_id=uuid.uuid4(),
                    )
                assert "Redis unavailable" in str(exc_info.value)


class TestRateLimitRedisFailure:
    @pytest.mark.asyncio
    async def test_redis_failure_blocks_rate_limit(self):
        """When Redis is unavailable for rate limiting, fail-closed."""
        policy = {"max_requests_per_minute": 10}
        engine = GovernanceEngine(policy)
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.incr = AsyncMock(side_effect=ConnectionError("Redis down"))
                with pytest.raises(GovernanceViolation) as exc_info:
                    await engine.check(
                        action="tool_call",
                        context={"tool_name": "test", "instance_id": "x"},
                        tenant_id=uuid.uuid4(),
                    )
                assert "Redis unavailable" in str(exc_info.value)


class TestSpendingTracking:
    @pytest.mark.asyncio
    async def test_track_spending_records_to_redis(self):
        with patch("app.agents.governance.redis_pool") as mock_redis:
            mock_redis.incrbyfloat = AsyncMock()
            mock_redis.expire = AsyncMock()
            await GovernanceEngine.track_spending(
                tenant_id=uuid.uuid4(),
                agent_id="agent1",
                instance_id="inst1",
                cost_usd=0.05,
            )
            assert mock_redis.incrbyfloat.call_count == 3  # run, day, month

    @pytest.mark.asyncio
    async def test_track_spending_best_effort_on_redis_failure(self):
        """track_spending should not raise on Redis failure."""
        with patch("app.agents.governance.redis_pool") as mock_redis:
            mock_redis.incrbyfloat = AsyncMock(side_effect=ConnectionError("Redis down"))
            # Should not raise
            await GovernanceEngine.track_spending(
                tenant_id=uuid.uuid4(),
                agent_id="agent1",
                instance_id="inst1",
                cost_usd=0.05,
            )


class TestEmptyPolicy:
    @pytest.mark.asyncio
    async def test_empty_policy_allows_everything(self):
        engine = GovernanceEngine({})
        with patch("app.agents.governance.emit", new_callable=AsyncMock):
            with patch("app.agents.governance.redis_pool") as mock_redis:
                mock_redis.incr = AsyncMock(return_value=1)
                mock_redis.expire = AsyncMock()
                await engine.check(
                    action="tool_call",
                    context={"tool_name": "anything", "instance_id": "x"},
                    tenant_id=uuid.uuid4(),
                )
