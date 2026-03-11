"""Agent-to-Agent (A2A) communication layer.

Provides inter-agent messaging via Redis for:
    - Direct messages between agent instances
    - Capability discovery (what can each agent do?)
    - Request/response patterns
    - Broadcast to agent groups

Inspired by Google's A2A protocol, adapted for Redis-backed messaging.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Redis key patterns — all keys include tenant_id for cross-tenant isolation.
_INBOX_KEY = "agent:a2a:inbox:{tenant_id}:{instance_id}"
_CAPABILITIES_KEY = "agent:a2a:caps:{tenant_id}:{instance_id}"
_GROUP_KEY = "agent:a2a:group:{tenant_id}:{group_name}"

# Maximum inbox size to prevent unbounded memory growth.
_MAX_INBOX_SIZE = 1000

# Allowed characters for group names to prevent Redis key injection.
import re
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


def _validate_group_name(group_name: str) -> None:
    """Validate group_name contains only safe characters for Redis keys."""
    if not _SAFE_NAME_RE.match(group_name):
        raise ValueError(
            f"Invalid group_name '{group_name}': must be 1-128 alphanumeric "
            "characters, dots, hyphens, or underscores."
        )


@dataclass
class A2AMessage:
    """A message between two agent instances."""

    id: str = ""
    from_instance: str = ""
    to_instance: str = ""
    message_type: str = "request"  # "request", "response", "broadcast", "notification"
    content: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""  # Links request to response
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id or uuid.uuid4().hex,
            "from_instance": self.from_instance,
            "to_instance": self.to_instance,
            "message_type": self.message_type,
            "content": self.content,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp or time.time(),
        }


@dataclass
class AgentCapability:
    """Describes what an agent instance can do."""

    instance_id: str
    agent_name: str
    capabilities: list[str]  # e.g. ["summarize", "translate", "code_review"]
    model: str = ""
    status: str = "available"  # "available", "busy", "offline"


class A2ACommunicator:
    """Agent-to-Agent communication via Redis.

    Each agent instance has an inbox (Redis List) for receiving messages.
    Messages are JSON-serialized and support request/response correlation.
    """

    async def send(
        self,
        *,
        from_instance: uuid.UUID,
        to_instance: uuid.UUID,
        tenant_id: uuid.UUID,
        content: dict[str, Any],
        message_type: str = "request",
        correlation_id: str | None = None,
    ) -> str:
        """Send a message to another agent instance.

        Both sender and recipient must belong to the same tenant.
        Returns the message ID.
        """
        msg = A2AMessage(
            id=uuid.uuid4().hex,
            from_instance=str(from_instance),
            to_instance=str(to_instance),
            message_type=message_type,
            content=content,
            correlation_id=correlation_id or uuid.uuid4().hex,
            timestamp=time.time(),
        )

        inbox_key = _INBOX_KEY.format(tenant_id=tenant_id, instance_id=to_instance)
        await redis_pool.lpush(inbox_key, json.dumps(msg.to_dict(), default=str))
        # Trim inbox to prevent unbounded growth.
        await redis_pool.ltrim(inbox_key, 0, _MAX_INBOX_SIZE - 1)
        # Expire inbox after 24 hours of inactivity
        await redis_pool.expire(inbox_key, 86400)

        logger.debug(
            "a2a_message_sent",
            from_instance=str(from_instance),
            to_instance=str(to_instance),
            message_type=message_type,
            msg_id=msg.id,
        )
        return msg.id

    async def receive(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        timeout_seconds: int = 0,
        count: int = 10,
        max_age_seconds: int | None = None,
    ) -> list[A2AMessage]:
        """Receive messages from an agent's inbox.

        If timeout_seconds > 0, blocks until a message arrives or timeout.
        Otherwise returns immediately with available messages.
        If max_age_seconds is set, messages older than threshold are discarded.
        """
        inbox_key = _INBOX_KEY.format(tenant_id=tenant_id, instance_id=instance_id)

        raw_messages = []
        if timeout_seconds > 0:
            # Blocking pop
            result = await redis_pool.brpop(inbox_key, timeout=timeout_seconds)
            if result:
                _, raw = result
                raw_messages.append(self._parse_message(raw))
        else:
            # Non-blocking: pop up to `count` messages
            for _ in range(count):
                raw = await redis_pool.rpop(inbox_key)
                if raw is None:
                    break
                raw_messages.append(self._parse_message(raw))

        # Filter out stale messages
        if max_age_seconds is not None and raw_messages:
            now = time.time()
            raw_messages = [
                m for m in raw_messages
                if (now - m.timestamp) <= max_age_seconds
            ]

        return raw_messages

    async def reply(
        self,
        original: A2AMessage,
        content: dict[str, Any],
        from_instance: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> str:
        """Send a reply to a received message, preserving correlation_id."""
        return await self.send(
            from_instance=from_instance,
            to_instance=uuid.UUID(original.from_instance),
            tenant_id=tenant_id,
            content=content,
            message_type="response",
            correlation_id=original.correlation_id,
        )

    async def broadcast(
        self,
        *,
        from_instance: uuid.UUID,
        tenant_id: uuid.UUID,
        group_name: str,
        content: dict[str, Any],
    ) -> int:
        """Broadcast a message to all agents in a group.

        Returns the number of agents messaged.
        """
        _validate_group_name(group_name)
        group_key = _GROUP_KEY.format(tenant_id=tenant_id, group_name=group_name)
        members = await redis_pool.smembers(group_key)

        count = 0
        for member_id in members:
            if member_id == str(from_instance):
                continue  # Don't message self
            await self.send(
                from_instance=from_instance,
                to_instance=uuid.UUID(member_id),
                tenant_id=tenant_id,
                content=content,
                message_type="broadcast",
            )
            count += 1

        return count

    # ── Group Management ───────────────────────────────────────────────

    async def join_group(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        group_name: str,
    ) -> None:
        """Add an agent instance to a communication group."""
        _validate_group_name(group_name)
        group_key = _GROUP_KEY.format(tenant_id=tenant_id, group_name=group_name)
        await redis_pool.sadd(group_key, str(instance_id))
        await redis_pool.expire(group_key, 86400)

    async def leave_group(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        group_name: str,
    ) -> None:
        """Remove an agent instance from a communication group."""
        _validate_group_name(group_name)
        group_key = _GROUP_KEY.format(tenant_id=tenant_id, group_name=group_name)
        await redis_pool.srem(group_key, str(instance_id))

    async def list_group_members(
        self,
        tenant_id: uuid.UUID,
        group_name: str,
    ) -> list[str]:
        """List all agent instances in a group."""
        _validate_group_name(group_name)
        group_key = _GROUP_KEY.format(tenant_id=tenant_id, group_name=group_name)
        return list(await redis_pool.smembers(group_key))

    # ── Capability Discovery ───────────────────────────────────────────

    async def register_capabilities(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        capability: AgentCapability,
    ) -> None:
        """Register an agent's capabilities for discovery."""
        caps_key = _CAPABILITIES_KEY.format(tenant_id=tenant_id, instance_id=instance_id)
        await redis_pool.set(
            caps_key,
            json.dumps({
                "instance_id": capability.instance_id,
                "agent_name": capability.agent_name,
                "capabilities": capability.capabilities,
                "model": capability.model,
                "status": capability.status,
            }),
            ex=3600,  # Expire after 1 hour
        )

    async def discover_capabilities(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> AgentCapability | None:
        """Look up an agent's registered capabilities."""
        caps_key = _CAPABILITIES_KEY.format(tenant_id=tenant_id, instance_id=instance_id)
        raw = await redis_pool.get(caps_key)
        if not raw:
            return None
        data = json.loads(raw)
        return AgentCapability(**data)

    async def find_agents_with_capability(
        self,
        tenant_id: uuid.UUID,
        group_name: str,
        capability: str,
    ) -> list[AgentCapability]:
        """Find all agents in a group that have a specific capability.

        Filters out agents with status 'offline'.
        """
        members = await self.list_group_members(tenant_id, group_name)
        results = []
        for member_id in members:
            caps = await self.discover_capabilities(uuid.UUID(member_id), tenant_id)
            if caps and capability in caps.capabilities and caps.status != "offline":
                results.append(caps)
        return results

    # ── Inbox Management ──────────────────────────────────────────────

    async def inbox_size(self, instance_id: uuid.UUID, tenant_id: uuid.UUID) -> int:
        """Get the number of pending messages in an agent's inbox."""
        inbox_key = _INBOX_KEY.format(tenant_id=tenant_id, instance_id=instance_id)
        return await redis_pool.llen(inbox_key)

    async def clear_inbox(self, instance_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Clear all messages from an agent's inbox."""
        inbox_key = _INBOX_KEY.format(tenant_id=tenant_id, instance_id=instance_id)
        await redis_pool.delete(inbox_key)

    def _parse_message(self, raw: str | bytes) -> A2AMessage:
        """Parse a raw JSON message into an A2AMessage."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        return A2AMessage(**data)


# Module-level singleton
a2a = A2ACommunicator()
