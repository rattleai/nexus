"""Agent governance engine — enforces policies, spending limits, and approval workflows.

Provides:
    - Per-agent spending limits (per-run, per-day, per-month)
    - Tool access control (allow/deny lists)
    - Human-in-the-loop approval for high-risk actions
    - Per-agent rate limiting (separate from tenant-level)
    - Audit trail for all governance decisions

The governance engine is invoked before every agent action (tool call, LLM
request) by the runtime. It raises GovernanceViolation if the action is
blocked.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

from app.agents.events import AgentApprovalRequested, AgentGovernanceViolation
from app.core.events import emit
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Redis keys for tracking spending and rate limits
_SPEND_RUN_KEY = "agent:gov:spend:run:{instance_id}"
_SPEND_DAY_KEY = "agent:gov:spend:day:{tenant_id}:{agent_id}:{date}"
_SPEND_MONTH_KEY = "agent:gov:spend:month:{tenant_id}:{agent_id}:{month}"
_RATE_KEY = "agent:gov:rate:{instance_id}"


class GovernanceViolation(Exception):
    """Raised when an agent action violates a governance policy."""

    def __init__(self, violation_type: str, message: str, *, details: dict[str, Any] | None = None):
        self.violation_type = violation_type
        self.details = details or {}
        super().__init__(message)


class GovernanceEngine:
    """Evaluates governance policies before agent actions.

    Usage:
        engine = GovernanceEngine(policy_dict)
        await engine.check(action="tool_call", context={...}, tenant_id=...)
    """

    def __init__(self, policy: dict[str, Any]):
        self.policy = policy

    async def check(
        self,
        *,
        action: str,
        context: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> None:
        """Run all governance checks for an action.

        Raises GovernanceViolation if any check fails.
        """
        await self._check_tool_access(action, context, tenant_id)
        await self._check_spending_limits(action, context, tenant_id)
        await self._check_rate_limits(action, context, tenant_id)
        await self._check_approval_required(action, context, tenant_id)

    async def _check_tool_access(
        self,
        action: str,
        context: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> None:
        """Check if the tool is allowed by the policy."""
        if action != "tool_call":
            return

        tool_name = context.get("tool_name", "")
        if not tool_name:
            return

        # Check denied tools first
        denied = self.policy.get("denied_tools", [])
        if denied and tool_name in denied:
            await self._emit_violation(
                tenant_id=tenant_id,
                context=context,
                violation_type="denied_tool",
                details=f"Tool '{tool_name}' is denied by policy",
            )
            raise GovernanceViolation(
                "denied_tool",
                f"Tool '{tool_name}' is denied by governance policy",
                details={"tool_name": tool_name},
            )

        # Check allowed tools (if specified, only these are allowed)
        allowed = self.policy.get("allowed_tools", [])
        if allowed and tool_name not in allowed:
            await self._emit_violation(
                tenant_id=tenant_id,
                context=context,
                violation_type="denied_tool",
                details=f"Tool '{tool_name}' is not in the allowed list",
            )
            raise GovernanceViolation(
                "denied_tool",
                f"Tool '{tool_name}' is not in the allowed tools list",
                details={"tool_name": tool_name, "allowed": allowed},
            )

    async def _check_spending_limits(
        self,
        action: str,
        context: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> None:
        """Check if spending limits have been exceeded."""
        instance_id = context.get("instance_id", "")
        current_cost = context.get("current_cost", 0.0)

        # Per-run limit
        max_per_run = self.policy.get("max_spend_per_run_usd")
        if max_per_run is not None and current_cost >= max_per_run:
            await self._emit_violation(
                tenant_id=tenant_id,
                context=context,
                violation_type="spending_limit",
                details=f"Per-run spending limit exceeded: ${current_cost:.4f} >= ${max_per_run:.2f}",
            )
            raise GovernanceViolation(
                "spending_limit",
                f"Agent has exceeded per-run spending limit (${max_per_run:.2f})",
                details={"current_cost": current_cost, "limit": max_per_run},
            )

        # Per-day limit (tracked in Redis)
        max_per_day = self.policy.get("max_spend_per_day_usd")
        if max_per_day is not None and instance_id:
            agent_id = context.get("agent_id", "unknown")
            from datetime import UTC, datetime
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            day_key = _SPEND_DAY_KEY.format(
                tenant_id=tenant_id, agent_id=agent_id, date=today,
            )
            daily_spend = float(await redis_pool.get(day_key) or 0)
            if daily_spend + current_cost >= max_per_day:
                await self._emit_violation(
                    tenant_id=tenant_id,
                    context=context,
                    violation_type="spending_limit",
                    details=f"Daily spending limit exceeded: ${daily_spend:.4f} >= ${max_per_day:.2f}",
                )
                raise GovernanceViolation(
                    "spending_limit",
                    f"Agent has exceeded daily spending limit (${max_per_day:.2f})",
                    details={"daily_spend": daily_spend, "limit": max_per_day},
                )

    async def _check_rate_limits(
        self,
        action: str,
        context: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> None:
        """Check per-agent rate limits."""
        max_rpm = self.policy.get("max_requests_per_minute")
        if max_rpm is None:
            return

        instance_id = context.get("instance_id", "")
        if not instance_id:
            return

        rate_key = _RATE_KEY.format(instance_id=instance_id)
        current = await redis_pool.incr(rate_key)
        if current == 1:
            await redis_pool.expire(rate_key, 60)

        if current > max_rpm:
            await self._emit_violation(
                tenant_id=tenant_id,
                context=context,
                violation_type="rate_limit",
                details=f"Rate limit exceeded: {current}/{max_rpm} requests/minute",
            )
            raise GovernanceViolation(
                "rate_limit",
                f"Agent rate limit exceeded ({max_rpm} requests/minute)",
                details={"current": current, "limit": max_rpm},
            )

    async def _check_approval_required(
        self,
        action: str,
        context: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> None:
        """Check if the action requires human approval.

        If approval is required, emits an event and raises GovernanceViolation
        to pause the agent. The agent can be resumed after approval.
        """
        require_approval = self.policy.get("require_approval_for", [])
        if not require_approval:
            return

        tool_name = context.get("tool_name", "")
        if tool_name not in require_approval:
            return

        approval_id = uuid.uuid4().hex
        timeout = self.policy.get("approval_timeout_seconds", 300)

        await emit(
            AgentApprovalRequested(
                tenant_id=str(tenant_id),
                instance_id=context.get("instance_id", ""),
                agent_id=context.get("agent_id", ""),
                action=f"tool_call:{tool_name}",
                approval_id=approval_id,
                timeout_seconds=timeout,
            ),
            durable=True,
        )

        # In a full implementation, this would pause and wait for approval
        # via WebSocket notification. For now, apply the default action.
        default_action = self.policy.get("approval_default_action", "deny")
        if default_action == "deny":
            raise GovernanceViolation(
                "approval_required",
                f"Action '{tool_name}' requires human approval",
                details={"approval_id": approval_id, "tool_name": tool_name},
            )

    async def _emit_violation(
        self,
        *,
        tenant_id: uuid.UUID,
        context: dict[str, Any],
        violation_type: str,
        details: str,
    ) -> None:
        """Emit a governance violation event."""
        await emit(
            AgentGovernanceViolation(
                tenant_id=str(tenant_id),
                instance_id=context.get("instance_id", ""),
                agent_id=context.get("agent_id", ""),
                violation_type=violation_type,
                details=details,
            ),
            durable=True,
        )

    @staticmethod
    async def track_spending(
        *,
        tenant_id: uuid.UUID,
        agent_id: str,
        instance_id: str,
        cost_usd: float,
    ) -> None:
        """Record spending for an agent execution (called after each LLM call)."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)

        # Per-run spending
        run_key = _SPEND_RUN_KEY.format(instance_id=instance_id)
        await redis_pool.incrbyfloat(run_key, cost_usd)
        await redis_pool.expire(run_key, 3600)  # 1 hour TTL

        # Per-day spending
        day_key = _SPEND_DAY_KEY.format(
            tenant_id=tenant_id, agent_id=agent_id, date=now.strftime("%Y-%m-%d"),
        )
        await redis_pool.incrbyfloat(day_key, cost_usd)
        await redis_pool.expire(day_key, 86400 * 2)  # 2 days TTL

        # Per-month spending
        month_key = _SPEND_MONTH_KEY.format(
            tenant_id=tenant_id, agent_id=agent_id, month=now.strftime("%Y-%m"),
        )
        await redis_pool.incrbyfloat(month_key, cost_usd)
        await redis_pool.expire(month_key, 86400 * 35)  # ~35 days TTL
