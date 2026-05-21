"""Agent governance engine — enforces policies, spending limits, and approval workflows.

Provides:
    - Per-agent spending limits (per-run, per-day, per-month)
    - Tool access control (allow/deny lists)
    - Human-in-the-loop approval for high-risk actions
    - Per-agent rate limiting (separate from tenant-level)
    - Audit trail for all governance decisions

The governance engine is invoked before every agent action (tool call, LLM
request) by the runtime. It raises GovernanceViolationError if the action is
blocked.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from typing import Any

import structlog

from app.agents.events import AgentApprovalRequested, AgentGovernanceViolation
from app.core.events import emit
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()


def _matches_tool_list(tool_name: str, patterns: list[str]) -> bool:
    """Check if a tool name matches any entry in a pattern list.

    Supports exact matches and fnmatch-style wildcards for
    connector tool patterns like ``connector:slack:*``.
    """
    if tool_name in patterns:
        return True
    # Only do wildcard matching if any pattern contains a glob character
    if any("*" in p or "?" in p for p in patterns):
        from fnmatch import fnmatch

        return any(fnmatch(tool_name, p) for p in patterns)
    return False


# Redis keys for tracking spending and rate limits
_SPEND_RUN_KEY = "agent:gov:spend:run:{instance_id}"
_SPEND_DAY_KEY = "agent:gov:spend:day:{tenant_id}:{agent_id}:{date}"
_SPEND_MONTH_KEY = "agent:gov:spend:month:{tenant_id}:{agent_id}:{month}"
_RATE_KEY = "agent:gov:rate:{tenant_id}:{instance_id}"
_RATE_AGENT_KEY = "agent:gov:rate:agent:{tenant_id}:{agent_id}"

# Redis keys for approval queue
_APPROVAL_KEY = "agent:gov:approval:{approval_id}"
_APPROVAL_PENDING_KEY = "agent:gov:approvals:pending:{tenant_id}"


class GovernanceViolationError(Exception):
    """Raised when an agent action violates a governance policy."""

    def __init__(self, violation_type: str, message: str, *, details: dict[str, Any] | None = None):
        self.violation_type = violation_type
        self.details = details or {}
        super().__init__(message)


# Atomic Lua script that checks spending AND increments in one operation.
# Prevents TOCTOU race: if the check passes, the amount is atomically added.
# Returns new total if within limit, or -1 if the limit would be exceeded.
# Also sets TTL on first write.
_CHECK_AND_INCREMENT_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local amount = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
if current + amount > limit then
    return -1
end
local new_total = current + amount
redis.call('SET', KEYS[1], new_total)
if ttl > 0 then
    redis.call('EXPIRE', KEYS[1], ttl)
end
return new_total
"""

# Read-only check (no increment) for per-run checks where cost is already tracked.
_CHECK_SPENDING_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local estimated = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
if current + estimated >= limit then
    return -1
end
return 0
"""


async def _atomic_check_and_increment(
    key: str,
    amount: float,
    limit: float,
    ttl_seconds: int = 0,
) -> int:
    """Atomically check spending limit AND increment in a single Lua call.

    Prevents TOCTOU races by merging check + track into one atomic operation.
    Returns new total if within limit, or -1 if limit would be exceeded.
    Uses Redis server-side Lua scripting (not Python eval).
    """
    # redis_pool.eval runs a Lua script on the Redis server (not Python eval)
    result = await redis_pool.eval(
        _CHECK_AND_INCREMENT_LUA,
        1,  # number of keys
        key,  # KEYS[1]
        str(amount),  # ARGV[1]
        str(limit),  # ARGV[2]
        str(ttl_seconds),  # ARGV[3]
    )
    return int(result)


async def _atomic_spend_check(
    key: str,
    estimated_cost: float,
    limit: float,
) -> int:
    """Atomically check whether spending would exceed the limit (read-only).

    Uses Redis server-side Lua scripting for atomic read+compare.
    Does NOT modify the key.
    Returns 0 if within bounds, -1 if limit would be exceeded.
    """
    # redis_pool.eval runs a Lua script on the Redis server (not Python eval)
    result = await redis_pool.eval(
        _CHECK_SPENDING_LUA,
        1,  # number of keys
        key,  # KEYS[1]
        str(estimated_cost),  # ARGV[1]
        str(limit),  # ARGV[2]
    )
    return int(result)


class GovernanceEngine:
    """Evaluates governance policies before agent actions.

    Usage:
        engine = GovernanceEngine(policy_dict)
        await engine.check(action="tool_call", context={...}, tenant_id=...)
    """

    def __init__(self, policy: dict[str, Any]):
        self.policy = policy
        # Eagerly resolve capability-level deny/approval to tool names
        # so the hot-path check remains a set membership test.
        self._denied_cap_tools: set[str] = set()
        self._approval_cap_tools: set[str] = set()
        denied_caps = policy.get("denied_capabilities", [])
        approval_caps = policy.get("require_approval_for_capabilities", [])
        if denied_caps or approval_caps:
            from app.agents.capabilities import capability_resolver

            if denied_caps:
                self._denied_cap_tools = capability_resolver.resolve(denied_caps)
            if approval_caps:
                self._approval_cap_tools = capability_resolver.resolve(approval_caps)

    async def check(
        self,
        *,
        action: str,
        context: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> None:
        """Run all governance checks for an action.

        Raises GovernanceViolationError if any check fails.
        """
        await self._check_tool_access(action, context, tenant_id)
        await self._check_spending_limits(action, context, tenant_id)
        await self._check_rate_limits(action, context, tenant_id)
        await self._check_db_flooding(action, context, tenant_id)
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

        # Check denied tools first (raw tool names, with wildcard support)
        denied = self.policy.get("denied_tools", [])
        if denied and _matches_tool_list(tool_name, denied):
            await self._emit_violation(
                tenant_id=tenant_id,
                context=context,
                violation_type="denied_tool",
                details=f"Tool '{tool_name}' is denied by policy",
            )
            raise GovernanceViolationError(
                "denied_tool",
                f"Tool '{tool_name}' is denied by governance policy",
                details={"tool_name": tool_name},
            )

        # Check denied capabilities (resolved at init)
        if self._denied_cap_tools and tool_name in self._denied_cap_tools:
            await self._emit_violation(
                tenant_id=tenant_id,
                context=context,
                violation_type="denied_tool",
                details=f"Tool '{tool_name}' is denied by capability policy",
            )
            raise GovernanceViolationError(
                "denied_tool",
                f"Tool '{tool_name}' is denied by capability governance policy",
                details={"tool_name": tool_name},
            )

        # Check allowed tools (if specified, only these are allowed; supports wildcards)
        allowed = self.policy.get("allowed_tools", [])
        if allowed and not _matches_tool_list(tool_name, allowed):
            await self._emit_violation(
                tenant_id=tenant_id,
                context=context,
                violation_type="denied_tool",
                details=f"Tool '{tool_name}' is not in the allowed list",
            )
            raise GovernanceViolationError(
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
            raise GovernanceViolationError(
                "spending_limit",
                f"Agent has exceeded per-run spending limit (${max_per_run:.2f})",
                details={"current_cost": current_cost, "limit": max_per_run},
            )

        # Per-day limit — atomic check-and-increment via Lua script.
        # Merges the check + spending tracking into a single atomic operation
        # to prevent TOCTOU races between concurrent requests.
        # Fail-closed: if Redis is unavailable, block the action.
        max_per_day = self.policy.get("max_spend_per_day_usd")
        if max_per_day is not None and instance_id:
            agent_id = context.get("agent_id", "unknown")
            estimated_cost = context.get("estimated_cost", 0.01)
            from datetime import UTC, datetime

            today = datetime.now(UTC).strftime("%Y-%m-%d")
            day_key = _SPEND_DAY_KEY.format(
                tenant_id=tenant_id,
                agent_id=agent_id,
                date=today,
            )
            try:
                lua_result = await _atomic_check_and_increment(
                    day_key,
                    estimated_cost,
                    max_per_day,
                    ttl_seconds=86400 * 2,
                )
            except Exception as exc:
                logger.error("governance_redis_unavailable", check="spending_limit", exc_info=True)
                raise GovernanceViolationError(
                    "spending_limit",
                    "Unable to verify spending limits (Redis unavailable). Action blocked.",
                    details={"reason": "redis_unavailable"},
                ) from exc
            if lua_result == -1:
                daily_spend = float(await redis_pool.get(day_key) or 0)
                await self._emit_violation(
                    tenant_id=tenant_id,
                    context=context,
                    violation_type="spending_limit",
                    details=f"Daily spending limit exceeded: ${daily_spend:.4f} >= ${max_per_day:.2f}",
                )
                raise GovernanceViolationError(
                    "spending_limit",
                    f"Agent has exceeded daily spending limit (${max_per_day:.2f})",
                    details={"daily_spend": daily_spend, "limit": max_per_day},
                )

        # Per-month limit — same atomic pattern as per-day
        max_per_month = self.policy.get("max_spend_per_month_usd")
        if max_per_month is not None and instance_id:
            agent_id = context.get("agent_id", "unknown")
            estimated_cost = context.get("estimated_cost", 0.01)
            from datetime import UTC, datetime

            this_month = datetime.now(UTC).strftime("%Y-%m")
            month_key = _SPEND_MONTH_KEY.format(
                tenant_id=tenant_id,
                agent_id=agent_id,
                month=this_month,
            )
            try:
                lua_result = await _atomic_check_and_increment(
                    month_key,
                    estimated_cost,
                    max_per_month,
                    ttl_seconds=86400 * 35,
                )
            except Exception as exc:
                logger.error("governance_redis_unavailable", check="monthly_spending_limit", exc_info=True)
                raise GovernanceViolationError(
                    "spending_limit",
                    "Unable to verify monthly spending limits (Redis unavailable). Action blocked.",
                    details={"reason": "redis_unavailable"},
                ) from exc
            if lua_result == -1:
                monthly_spend = float(await redis_pool.get(month_key) or 0)
                await self._emit_violation(
                    tenant_id=tenant_id,
                    context=context,
                    violation_type="spending_limit",
                    details=f"Monthly spending limit exceeded: ${monthly_spend:.4f} >= ${max_per_month:.2f}",
                )
                raise GovernanceViolationError(
                    "spending_limit",
                    f"Agent has exceeded monthly spending limit (${max_per_month:.2f})",
                    details={"monthly_spend": monthly_spend, "limit": max_per_month},
                )

    async def _check_rate_limits(
        self,
        action: str,
        context: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> None:
        """Check per-instance and per-agent (aggregate) rate limits."""
        max_rpm = self.policy.get("max_requests_per_minute")
        if max_rpm is None:
            return

        instance_id = context.get("instance_id", "")
        if not instance_id:
            return

        rate_key = _RATE_KEY.format(tenant_id=tenant_id, instance_id=instance_id)
        try:
            # Use a transactional pipeline (MULTI/EXEC) to make INCR + EXPIRE
            # atomic — avoids permanent keys if the process crashes mid-pipeline.
            pipe = redis_pool.pipeline(transaction=True)
            pipe.incr(rate_key)
            pipe.expire(rate_key, 60)  # Always refresh TTL
            results = await pipe.execute()
            current = results[0]
        except Exception as exc:
            # Fail-closed: if Redis is unavailable, block the action
            logger.error("governance_redis_unavailable", check="rate_limit", exc_info=True)
            raise GovernanceViolationError(
                "rate_limit",
                "Unable to verify rate limits (Redis unavailable). Action blocked.",
                details={"reason": "redis_unavailable"},
            ) from exc

        if current > max_rpm:
            await self._emit_violation(
                tenant_id=tenant_id,
                context=context,
                violation_type="rate_limit",
                details=f"Rate limit exceeded: {current}/{max_rpm} requests/minute",
            )
            raise GovernanceViolationError(
                "rate_limit",
                f"Agent rate limit exceeded ({max_rpm} requests/minute)",
                details={"current": current, "limit": max_rpm},
            )

        # Aggregate rate limit across ALL instances of the same agent definition.
        # Prevents N parallel instances from sending N * max_rpm requests/minute
        # to the LLM provider.
        max_agent_rpm = self.policy.get("max_agent_requests_per_minute")
        agent_id = context.get("agent_id", "")
        if max_agent_rpm is not None and agent_id:
            agent_rate_key = _RATE_AGENT_KEY.format(
                tenant_id=tenant_id,
                agent_id=agent_id,
            )
            try:
                pipe = redis_pool.pipeline(transaction=True)
                pipe.incr(agent_rate_key)
                pipe.expire(agent_rate_key, 60)
                results = await pipe.execute()
                agent_current = results[0]
            except Exception as exc:
                logger.error("governance_redis_unavailable", check="agent_rate_limit", exc_info=True)
                raise GovernanceViolationError(
                    "rate_limit",
                    "Unable to verify agent-level rate limits (Redis unavailable). Action blocked.",
                    details={"reason": "redis_unavailable"},
                ) from exc

            if agent_current > max_agent_rpm:
                await self._emit_violation(
                    tenant_id=tenant_id,
                    context=context,
                    violation_type="agent_rate_limit",
                    details=f"Agent-level rate limit exceeded: {agent_current}/{max_agent_rpm} requests/minute",
                )
                raise GovernanceViolationError(
                    "rate_limit",
                    f"Agent-level aggregate rate limit exceeded ({max_agent_rpm} requests/minute across all instances)",
                    details={"current": agent_current, "limit": max_agent_rpm, "scope": "agent"},
                )

    async def _check_approval_required(
        self,
        action: str,
        context: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> None:
        """Check if the action requires human approval.

        If approval is required:
        1. Creates an approval request in Redis with a TTL
        2. Emits an AgentApprovalRequested event for WebSocket/SSE push
        3. Polls Redis for the approval decision until timeout
        4. Raises GovernanceViolationError if denied or timed out
        """
        require_approval = self.policy.get("require_approval_for", [])
        tool_name = context.get("tool_name", "")

        # Check both raw tool names and capability-resolved tool names
        needs_approval = (require_approval and tool_name in require_approval) or (
            self._approval_cap_tools and tool_name in self._approval_cap_tools
        )
        if not needs_approval:
            return

        approval_id = uuid.uuid4().hex
        timeout = self.policy.get("approval_timeout_seconds", 300)
        instance_id = context.get("instance_id", "")
        agent_id = context.get("agent_id", "")
        default_action = self.policy.get("approval_default_action", "deny")

        # Store approval request in Redis for the approval queue
        approval_key = _APPROVAL_KEY.format(approval_id=approval_id)
        import json
        from datetime import UTC, datetime

        approval_data = json.dumps(
            {
                "approval_id": approval_id,
                "tenant_id": str(tenant_id),
                "instance_id": instance_id,
                "agent_id": agent_id,
                "action": f"tool_call:{tool_name}",
                "tool_name": tool_name,
                "context": {k: str(v) for k, v in context.items()},
                "status": "pending",
                "default_action": default_action,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        await redis_pool.setex(approval_key, timeout + 60, approval_data)

        # Add to tenant's pending approvals list
        pending_key = _APPROVAL_PENDING_KEY.format(tenant_id=tenant_id)
        await redis_pool.sadd(pending_key, approval_id)
        await redis_pool.expire(pending_key, timeout + 60)

        await emit(
            AgentApprovalRequested(
                tenant_id=str(tenant_id),
                instance_id=instance_id,
                agent_id=agent_id,
                action=f"tool_call:{tool_name}",
                approval_id=approval_id,
                timeout_seconds=timeout,
            ),
            durable=True,
        )

        # Wait for approval via Redis pub/sub (low-latency) with polling fallback
        decision = await self._wait_for_approval(approval_id, approval_key, timeout)

        # Clean up pending set
        await redis_pool.srem(pending_key, approval_id)

        if decision is None:
            # Timeout: apply default action
            from app.agents.events import AgentApprovalResolved

            await emit(
                AgentApprovalResolved(
                    tenant_id=str(tenant_id),
                    approval_id=approval_id,
                    decision="timeout",
                    resolved_by="system",
                ),
                durable=True,
            )
            decision = default_action

        if decision == "denied" or (decision != "approved" and default_action == "deny"):
            raise GovernanceViolationError(
                "approval_required",
                f"Action '{tool_name}' was {'denied' if decision == 'denied' else 'not approved (timeout)'}",
                details={"approval_id": approval_id, "tool_name": tool_name, "decision": decision},
            )

    async def _wait_for_approval(
        self,
        approval_id: str,
        approval_key: str,
        timeout: int,
    ) -> str | None:
        """Wait for an approval decision via Redis pub/sub with polling fallback.

        Uses pub/sub for near-instant notification when resolve_approval() is
        called. Falls back to polling every 5s if pub/sub fails to connect.
        Returns the decision ("approved"/"denied") or None on timeout.
        """
        import asyncio
        import json

        decision_event = asyncio.Event()
        decision_holder: list[str | None] = [None]
        channel_name = f"agent:approval:resolved:{approval_id}"

        async def _pubsub_listener() -> None:
            """Listen for pub/sub notification of approval resolution."""
            try:
                pubsub = redis_pool.pubsub()
                await pubsub.subscribe(channel_name)
                try:
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            data = message["data"]
                            if isinstance(data, bytes):
                                data = data.decode()
                            decision_holder[0] = data
                            decision_event.set()
                            return
                finally:
                    await pubsub.unsubscribe(channel_name)
                    await pubsub.aclose()
            except Exception:
                # Pub/sub failed — polling fallback will handle it
                logger.debug("approval_pubsub_failed", approval_id=approval_id)

        async def _polling_fallback() -> None:
            """Poll Redis key as fallback if pub/sub doesn't fire."""
            elapsed = 0.0
            while elapsed < timeout and not decision_event.is_set():
                await asyncio.sleep(3.0)
                elapsed += 3.0
                try:
                    raw = await redis_pool.get(approval_key)
                    if raw:
                        data = json.loads(raw)
                        if data.get("status") != "pending":
                            decision_holder[0] = data["status"]
                            decision_event.set()
                            return
                except Exception:
                    pass

        # Run pub/sub listener and polling fallback concurrently
        listener_task = asyncio.create_task(_pubsub_listener())
        poller_task = asyncio.create_task(_polling_fallback())

        try:
            await asyncio.wait_for(decision_event.wait(), timeout=timeout)
        except TimeoutError:
            pass
        finally:
            listener_task.cancel()
            poller_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener_task
            with contextlib.suppress(asyncio.CancelledError):
                await poller_task

        return decision_holder[0]

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

    async def _check_db_flooding(
        self,
        action: str,
        context: dict[str, Any],
        tenant_id: uuid.UUID,
    ) -> None:
        """Check for database flooding: idle transaction detection and connection reservation."""
        if action != "tool_call":
            return
        tool_name = context.get("tool_name", "")
        if tool_name not in ("db_query", "code_execute"):
            return

        instance_id = context.get("instance_id", "")
        if not instance_id:
            return

        # Check per-agent DB query rate (separate from general rate limiting)
        max_db_qpm = self.policy.get("max_queries_per_minute")
        if max_db_qpm is not None:
            rate_key = f"agent:gov:db_rate:{tenant_id}:{instance_id}"
            try:
                pipe = redis_pool.pipeline()
                pipe.incr(rate_key)
                pipe.expire(rate_key, 60)
                results = await pipe.execute()
                current = results[0]
            except Exception as exc:
                logger.error("governance_redis_unavailable", check="db_rate_limit", exc_info=True)
                raise GovernanceViolationError(
                    "db_rate_limit",
                    "Unable to verify DB rate limits (Redis unavailable). Action blocked.",
                    details={"reason": "redis_unavailable"},
                ) from exc

            if current > max_db_qpm:
                await self._emit_violation(
                    tenant_id=tenant_id,
                    context=context,
                    violation_type="db_rate_limit",
                    details=f"DB query rate limit exceeded: {current}/{max_db_qpm} queries/minute",
                )
                raise GovernanceViolationError(
                    "db_rate_limit",
                    f"Agent DB query rate limit exceeded ({max_db_qpm} queries/minute)",
                    details={"current": current, "limit": max_db_qpm},
                )

        # Check per-agent max result bytes
        max_result_bytes = self.policy.get("max_result_bytes_per_query")
        if max_result_bytes is not None:
            result_bytes = context.get("result_bytes", 0)
            if result_bytes > max_result_bytes:
                await self._emit_violation(
                    tenant_id=tenant_id,
                    context=context,
                    violation_type="db_result_size",
                    details=f"DB result size exceeded: {result_bytes}/{max_result_bytes} bytes",
                )
                raise GovernanceViolationError(
                    "db_result_size",
                    f"Agent DB result exceeds maximum ({max_result_bytes} bytes)",
                    details={"result_bytes": result_bytes, "limit": max_result_bytes},
                )

    @staticmethod
    async def track_spending(
        *,
        tenant_id: uuid.UUID,
        agent_id: str,
        instance_id: str,
        cost_usd: float,
    ) -> None:
        """Record spending for an agent execution (called after each LLM call).

        Best-effort: if Redis is unavailable, spending is logged but not tracked.
        The governance check will fail-closed (block) if it can't read spending,
        so missing a write here is safe — it only risks under-counting.
        """
        from datetime import UTC, datetime

        try:
            now = datetime.now(UTC)

            # Use a pipeline to batch all writes atomically, preventing
            # partial updates if the process dies mid-sequence.
            run_key = _SPEND_RUN_KEY.format(instance_id=instance_id)
            day_key = _SPEND_DAY_KEY.format(
                tenant_id=tenant_id,
                agent_id=agent_id,
                date=now.strftime("%Y-%m-%d"),
            )
            month_key = _SPEND_MONTH_KEY.format(
                tenant_id=tenant_id,
                agent_id=agent_id,
                month=now.strftime("%Y-%m"),
            )

            pipe = redis_pool.pipeline()
            pipe.incrbyfloat(run_key, cost_usd)
            pipe.expire(run_key, 3600)  # 1 hour TTL
            pipe.incrbyfloat(day_key, cost_usd)
            pipe.expire(day_key, 86400 * 2)  # 2 days TTL
            pipe.incrbyfloat(month_key, cost_usd)
            pipe.expire(month_key, 86400 * 35)  # ~35 days TTL
            await pipe.execute()
        except Exception:
            logger.error(
                "track_spending_failed",
                tenant_id=str(tenant_id),
                agent_id=agent_id,
                instance_id=instance_id,
                cost_usd=cost_usd,
                exc_info=True,
            )

    @staticmethod
    async def resolve_approval(
        *,
        approval_id: str,
        decision: str,
        resolved_by: str,
    ) -> dict[str, Any] | None:
        """Resolve a pending approval request.

        Args:
            approval_id: The approval request ID.
            decision: "approved" or "denied".
            resolved_by: User ID or email of the approver.

        Returns:
            The approval data if found and resolved, None if not found.
        """
        import json

        approval_key = _APPROVAL_KEY.format(approval_id=approval_id)

        # Use WATCH/MULTI/EXEC for optimistic locking to prevent TOCTOU
        # races where two concurrent approvers both read "pending" and
        # both write their decisions.
        from datetime import UTC, datetime

        max_retries = 3
        for _attempt in range(max_retries):
            try:
                async with redis_pool.pipeline(transaction=True) as pipe:
                    await pipe.watch(approval_key)
                    raw = await pipe.get(approval_key)
                    if not raw:
                        await pipe.unwatch()
                        return None

                    data = json.loads(raw)
                    if data.get("status") != "pending":
                        await pipe.unwatch()
                        return data  # Already resolved

                    data["status"] = decision
                    data["resolved_by"] = resolved_by
                    data["resolved_at"] = datetime.now(UTC).isoformat()

                    ttl = await pipe.ttl(approval_key)

                    pipe.multi()
                    if ttl > 0:
                        pipe.setex(approval_key, ttl, json.dumps(data))
                    else:
                        pipe.set(approval_key, json.dumps(data))
                    await pipe.execute()
                    break  # Success
            except Exception:
                # WatchError or connection error — retry
                if _attempt == max_retries - 1:
                    raise

        # Notify waiting agent via pub/sub (near-instant unblock)
        channel_name = f"agent:approval:resolved:{approval_id}"
        with contextlib.suppress(Exception):
            await redis_pool.publish(channel_name, decision)

        from app.agents.events import AgentApprovalResolved

        await emit(
            AgentApprovalResolved(
                tenant_id=data.get("tenant_id", ""),
                approval_id=approval_id,
                decision=decision,
                resolved_by=resolved_by,
            ),
            durable=True,
        )

        logger.info(
            "approval_resolved",
            approval_id=approval_id,
            decision=decision,
            resolved_by=resolved_by,
        )
        return data

    # ── Anti-Abuse & Graceful Degradation ──────────────────────────

    async def check_abuse_patterns(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_id: str,
        instance_id: str,
    ) -> dict[str, Any]:
        """Detect token abuse patterns: repeated governance violations, retry storms.

        Returns abuse detection result with recommended action.
        """
        abuse_key = f"agent:gov:abuse:{tenant_id}:{agent_id}"
        violation_key = f"agent:gov:violations:{tenant_id}:{agent_id}"

        try:
            # Count recent governance violations (last hour)
            pipe = redis_pool.pipeline()
            pipe.get(violation_key)
            pipe.get(abuse_key)
            results = await pipe.execute()

            violation_count = int(results[0]) if results[0] else 0
            abuse_score = int(results[1]) if results[1] else 0

            action = "none"
            if violation_count >= 10 or abuse_score >= 5:
                action = "suspend"
            elif violation_count >= 5 or abuse_score >= 3:
                action = "throttle"
            elif violation_count >= 3:
                action = "warn"

            return {
                "violation_count": violation_count,
                "abuse_score": abuse_score,
                "action": action,
            }
        except Exception:
            return {"violation_count": 0, "abuse_score": 0, "action": "none"}

    @staticmethod
    async def record_violation(
        tenant_id: uuid.UUID,
        agent_id: str,
    ) -> None:
        """Record a governance violation for abuse detection."""
        violation_key = f"agent:gov:violations:{tenant_id}:{agent_id}"
        try:
            pipe = redis_pool.pipeline()
            pipe.incr(violation_key)
            pipe.expire(violation_key, 3600)  # 1 hour window
            await pipe.execute()
        except Exception:
            logger.debug("violation_record_failed", exc_info=True)

    @staticmethod
    async def check_tenant_circuit_breaker(tenant_id: uuid.UUID) -> tuple[bool, str]:
        """Check if the tenant's agent circuit breaker is open.

        Returns (is_open, reason). When open, all agent execution for this tenant is paused.
        """
        cb_key = f"agent:gov:tenant_cb:{tenant_id}"
        try:
            raw = await redis_pool.get(cb_key)
            if raw:
                import json

                data = json.loads(raw)
                return True, data.get("reason", "Circuit breaker open")
            return False, ""
        except Exception:
            return False, ""

    @staticmethod
    async def trip_tenant_circuit_breaker(
        tenant_id: uuid.UUID,
        reason: str,
        duration_seconds: int = 300,
    ) -> None:
        """Trip the tenant-level circuit breaker, pausing all agent execution."""
        import json

        cb_key = f"agent:gov:tenant_cb:{tenant_id}"
        data = json.dumps(
            {
                "reason": reason,
                "tripped_at": time.time(),
                "duration": duration_seconds,
            }
        )
        try:
            await redis_pool.setex(cb_key, duration_seconds, data)
            logger.warning(
                "tenant_circuit_breaker_tripped",
                tenant_id=str(tenant_id),
                reason=reason,
                duration=duration_seconds,
            )
        except Exception:
            logger.error("tenant_cb_trip_failed", exc_info=True)

    @staticmethod
    async def apply_progressive_throttling(
        tenant_id: uuid.UUID,
        agent_id: str,
        instance_id: str,
    ) -> float:
        """Calculate progressive throttling delay for an agent.

        Instead of hard-blocking, progressively slow execution with exponential backoff.
        Returns delay in seconds (0 = no throttling).
        """
        throttle_key = f"agent:gov:throttle:{tenant_id}:{agent_id}"
        try:
            count = await redis_pool.get(throttle_key)
            if count:
                # Exponential backoff: 1s, 2s, 4s, 8s, max 30s
                delay = min(2 ** (int(count) - 1), 30)
                return float(delay)
        except Exception:
            pass
        return 0.0

    @staticmethod
    async def increment_throttle_counter(
        tenant_id: uuid.UUID,
        agent_id: str,
    ) -> None:
        """Increment the throttle counter for progressive throttling."""
        throttle_key = f"agent:gov:throttle:{tenant_id}:{agent_id}"
        try:
            pipe = redis_pool.pipeline()
            pipe.incr(throttle_key)
            pipe.expire(throttle_key, 300)  # Reset after 5 min of good behavior
            await pipe.execute()
        except Exception:
            pass

    @staticmethod
    async def list_pending_approvals(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        """List all pending approval requests for a tenant."""
        import json

        pending_key = _APPROVAL_PENDING_KEY.format(tenant_id=tenant_id)
        approval_ids = await redis_pool.smembers(pending_key)

        approvals = []
        for aid in approval_ids:
            aid_str = aid if isinstance(aid, str) else aid.decode()
            approval_key = _APPROVAL_KEY.format(approval_id=aid_str)
            raw = await redis_pool.get(approval_key)
            if raw:
                data = json.loads(raw)
                if data.get("status") == "pending":
                    approvals.append(data)
                else:
                    # Clean up resolved entries from pending set
                    await redis_pool.srem(pending_key, aid_str)

        return approvals
