"""Agent memory system — short-term (Redis) and long-term (PostgreSQL) memory.

Provides three tiers of memory:
    1. Short-term: Redis-backed session state (conversation history, scratchpad)
    2. Long-term: PostgreSQL key-value store with optional vector embeddings
    3. Shared: Redis-based shared state for multi-agent workflows

All memory is tenant-scoped and instance-scoped for isolation.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.events import AgentMemoryUpdated
from app.agents.models import AgentMemoryEntry
from app.core.events import emit
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Redis key patterns
_SHORT_TERM_KEY = "agent:memory:short:{instance_id}:{session_id}"
_SHARED_KEY = "agent:memory:shared:{tenant_id}:{workflow_id}"


class AgentMemoryManager:
    """Unified memory manager for agent instances.

    Handles short-term (Redis), long-term (PostgreSQL), and shared (Redis)
    memory with consistent interface and tenant isolation.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Short-Term Memory (Redis) ──────────────────────────────────────

    async def get_short_term(
        self,
        instance_id: uuid.UUID,
        session_id: uuid.UUID,
        key: str,
    ) -> Any | None:
        """Read a value from short-term (session) memory."""
        redis_key = _SHORT_TERM_KEY.format(
            instance_id=instance_id, session_id=session_id,
        )
        raw = await redis_pool.hget(redis_key, key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set_short_term(
        self,
        instance_id: uuid.UUID,
        session_id: uuid.UUID,
        key: str,
        value: Any,
        *,
        ttl_seconds: int = 3600,
    ) -> None:
        """Write a value to short-term (session) memory."""
        redis_key = _SHORT_TERM_KEY.format(
            instance_id=instance_id, session_id=session_id,
        )
        serialized = json.dumps(value, default=str)
        await redis_pool.hset(redis_key, key, serialized)
        await redis_pool.expire(redis_key, ttl_seconds)

    async def get_all_short_term(
        self,
        instance_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Read all short-term memory for a session."""
        redis_key = _SHORT_TERM_KEY.format(
            instance_id=instance_id, session_id=session_id,
        )
        raw = await redis_pool.hgetall(redis_key)
        result = {}
        for k, v in raw.items():
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
        return result

    async def clear_short_term(
        self,
        instance_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> None:
        """Clear all short-term memory for a session."""
        redis_key = _SHORT_TERM_KEY.format(
            instance_id=instance_id, session_id=session_id,
        )
        await redis_pool.delete(redis_key)

    # ── Long-Term Memory (PostgreSQL) ──────────────────────────────────

    async def get_long_term(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        key: str,
        namespace: str = "default",
    ) -> dict[str, Any] | None:
        """Read a value from long-term (persistent) memory."""
        stmt = select(AgentMemoryEntry).where(
            AgentMemoryEntry.instance_id == instance_id,
            AgentMemoryEntry.tenant_id == tenant_id,
            AgentMemoryEntry.namespace == namespace,
            AgentMemoryEntry.key == key,
        )
        result = await self.db.execute(stmt)
        entry = result.scalar_one_or_none()
        return entry.value if entry else None

    async def set_long_term(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        key: str,
        value: dict[str, Any],
        *,
        namespace: str = "default",
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
    ) -> AgentMemoryEntry:
        """Write a value to long-term (persistent) memory.

        Upserts: creates if not exists, updates if exists.
        """
        stmt = select(AgentMemoryEntry).where(
            AgentMemoryEntry.instance_id == instance_id,
            AgentMemoryEntry.tenant_id == tenant_id,
            AgentMemoryEntry.namespace == namespace,
            AgentMemoryEntry.key == key,
        )
        result = await self.db.execute(stmt)
        entry = result.scalar_one_or_none()

        if entry:
            entry.value = value
            if embedding is not None:
                entry.embedding = embedding
                entry.embedding_model = embedding_model
            entry.updated_at = datetime.now(UTC)
        else:
            entry = AgentMemoryEntry(
                tenant_id=tenant_id,
                instance_id=instance_id,
                namespace=namespace,
                key=key,
                value=value,
                embedding=embedding,
                embedding_model=embedding_model,
            )
            self.db.add(entry)

        await self.db.flush()

        await emit(
            AgentMemoryUpdated(
                tenant_id=str(tenant_id),
                instance_id=str(instance_id),
                namespace=namespace,
                key=key,
                action="set",
            ),
            durable=True,
        )

        return entry

    async def list_long_term(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        namespace: str = "default",
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentMemoryEntry]:
        """List long-term memory entries for an instance."""
        stmt = (
            select(AgentMemoryEntry)
            .where(
                AgentMemoryEntry.instance_id == instance_id,
                AgentMemoryEntry.tenant_id == tenant_id,
                AgentMemoryEntry.namespace == namespace,
            )
            .order_by(AgentMemoryEntry.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_long_term(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        key: str,
        namespace: str = "default",
    ) -> bool:
        """Delete a specific long-term memory entry."""
        stmt = delete(AgentMemoryEntry).where(
            AgentMemoryEntry.instance_id == instance_id,
            AgentMemoryEntry.tenant_id == tenant_id,
            AgentMemoryEntry.namespace == namespace,
            AgentMemoryEntry.key == key,
        )
        result = await self.db.execute(stmt)
        deleted = result.rowcount > 0

        if deleted:
            await emit(
                AgentMemoryUpdated(
                    tenant_id=str(tenant_id),
                    instance_id=str(instance_id),
                    namespace=namespace,
                    key=key,
                    action="delete",
                ),
                durable=True,
            )

        return deleted

    async def clear_long_term(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        namespace: str | None = None,
    ) -> int:
        """Clear all long-term memory for an instance (optionally within a namespace)."""
        conditions = [
            AgentMemoryEntry.instance_id == instance_id,
            AgentMemoryEntry.tenant_id == tenant_id,
        ]
        if namespace:
            conditions.append(AgentMemoryEntry.namespace == namespace)

        stmt = delete(AgentMemoryEntry).where(*conditions)
        result = await self.db.execute(stmt)

        await emit(
            AgentMemoryUpdated(
                tenant_id=str(tenant_id),
                instance_id=str(instance_id),
                namespace=namespace or "*",
                key="*",
                action="clear",
            ),
            durable=True,
        )

        return result.rowcount

    async def search_by_embedding(
        self,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        query_embedding: list[float],
        *,
        namespace: str = "default",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search long-term memory by vector similarity.

        Uses cosine similarity on JSONB-stored embeddings.
        For production, use pgvector extension for native vector ops.
        This implementation provides a compatible interface that works
        without pgvector installed.
        """
        # Fetch all entries with embeddings in the namespace
        stmt = (
            select(AgentMemoryEntry)
            .where(
                AgentMemoryEntry.instance_id == instance_id,
                AgentMemoryEntry.tenant_id == tenant_id,
                AgentMemoryEntry.namespace == namespace,
                AgentMemoryEntry.embedding.isnot(None),
            )
        )
        result = await self.db.execute(stmt)
        entries = list(result.scalars().all())

        # Compute cosine similarity in Python (fallback for non-pgvector setups)
        scored = []
        for entry in entries:
            emb = entry.embedding
            if isinstance(emb, list) and len(emb) == len(query_embedding):
                score = _cosine_similarity(query_embedding, emb)
                scored.append({"entry": entry, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)

        return [
            {
                "key": item["entry"].key,
                "value": item["entry"].value,
                "score": item["score"],
                "namespace": item["entry"].namespace,
            }
            for item in scored[:limit]
        ]

    # ── Shared Memory (Redis) ─────────────────────────────────────────

    async def get_shared(
        self,
        tenant_id: uuid.UUID,
        workflow_id: uuid.UUID,
        key: str,
    ) -> Any | None:
        """Read a value from shared (workflow-level) memory."""
        redis_key = _SHARED_KEY.format(tenant_id=tenant_id, workflow_id=workflow_id)
        raw = await redis_pool.hget(redis_key, key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set_shared(
        self,
        tenant_id: uuid.UUID,
        workflow_id: uuid.UUID,
        key: str,
        value: Any,
        *,
        ttl_seconds: int = 86400,
    ) -> None:
        """Write a value to shared (workflow-level) memory."""
        redis_key = _SHARED_KEY.format(tenant_id=tenant_id, workflow_id=workflow_id)
        serialized = json.dumps(value, default=str)
        await redis_pool.hset(redis_key, key, serialized)
        await redis_pool.expire(redis_key, ttl_seconds)

    async def clear_shared(
        self,
        tenant_id: uuid.UUID,
        workflow_id: uuid.UUID,
    ) -> None:
        """Clear all shared memory for a workflow."""
        redis_key = _SHARED_KEY.format(tenant_id=tenant_id, workflow_id=workflow_id)
        await redis_pool.delete(redis_key)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
