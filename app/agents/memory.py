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
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.events import AgentMemoryUpdated
from app.agents.models import AgentMemoryEntry
from app.core.events import emit
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Redis key patterns
_SHORT_TERM_KEY = "agent:memory:short:{instance_id}:{session_id}"
_SHARED_KEY = "agent:memory:shared:{tenant_id}:{workflow_id}"

# Cap for fallback Python-based similarity computation.
# For production workloads with larger memory stores, use the pgvector extension.
_MAX_EMBEDDING_CANDIDATES = 1000


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

    # Redis Lua script for atomic check-and-set with cap enforcement.
    # Returns 1 if the value was set, 0 if the cap was reached and key is new.
    _SET_SHORT_TERM_LUA = """
local size = redis.call('HLEN', KEYS[1])
if size >= tonumber(ARGV[3]) and redis.call('HEXISTS', KEYS[1], ARGV[1]) == 0 then
    return 0
end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
return 1
"""

    async def set_short_term(
        self,
        instance_id: uuid.UUID,
        session_id: uuid.UUID,
        key: str,
        value: Any,
        *,
        ttl_seconds: int = 3600,
        max_entries: int = 100,
    ) -> None:
        """Write a value to short-term (session) memory.

        Uses a Redis Lua script for atomic cap enforcement to prevent
        concurrent writes from exceeding the cap.
        """
        from app.config import settings

        redis_key = _SHORT_TERM_KEY.format(
            instance_id=instance_id, session_id=session_id,
        )

        cap = max_entries or settings.AGENT_MEMORY_SHORT_MAX_ENTRIES
        serialized = json.dumps(value, default=str)

        # NOTE: redis_pool.eval() runs a server-side Lua script atomically
        # on the Redis server — this is NOT Python eval().
        result = await redis_pool.eval(
            self._SET_SHORT_TERM_LUA,
            1,  # number of keys
            redis_key,  # KEYS[1]
            key,  # ARGV[1] - hash field name
            serialized,  # ARGV[2] - value
            str(cap),  # ARGV[3] - max entries
            str(ttl_seconds),  # ARGV[4] - TTL
        )

        if result == 0:
            logger.warning(
                "short_term_memory_full",
                instance_id=str(instance_id),
                session_id=str(session_id),
                cap=cap,
            )

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
            or_(AgentMemoryEntry.expires_at.is_(None), AgentMemoryEntry.expires_at > datetime.now(UTC)),
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

        Uses INSERT ... ON CONFLICT DO UPDATE for atomic upsert,
        avoiding TOCTOU race between SELECT and INSERT.
        """
        # Validate embedding dimensions and types
        if embedding is not None:
            from app.config import settings
            expected_dims = settings.AGENT_MEMORY_VECTOR_DIMENSIONS
            if not isinstance(embedding, list):
                raise ValueError("Embedding must be a list of floats")
            if len(embedding) != expected_dims:
                raise ValueError(
                    f"Embedding dimension mismatch: got {len(embedding)}, "
                    f"expected {expected_dims}"
                )
            if not all(isinstance(v, (int, float)) for v in embedding):
                raise ValueError("All embedding values must be numeric (int or float)")
            # Ensure all values are finite
            import math
            if any(math.isnan(v) or math.isinf(v) for v in embedding):
                raise ValueError("Embedding contains NaN or Inf values")

        insert_values = {
            "tenant_id": tenant_id,
            "instance_id": instance_id,
            "namespace": namespace,
            "key": key,
            "value": value,
        }
        if embedding is not None:
            insert_values["embedding"] = embedding
            insert_values["embedding_model"] = embedding_model

        stmt = pg_insert(AgentMemoryEntry).values(**insert_values)

        # ON CONFLICT on the unique constraint (instance_id, namespace, key)
        update_set = {"value": value, "updated_at": datetime.now(UTC)}
        if embedding is not None:
            update_set["embedding"] = embedding
            update_set["embedding_model"] = embedding_model

        stmt = stmt.on_conflict_do_update(
            constraint="uq_agent_memory_instance_ns_key",
            set_=update_set,
        ).returning(AgentMemoryEntry)

        result = await self.db.execute(stmt)
        entry = result.scalar_one()

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
                or_(AgentMemoryEntry.expires_at.is_(None), AgentMemoryEntry.expires_at > datetime.now(UTC)),
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
        stmt = (
            select(AgentMemoryEntry)
            .where(
                AgentMemoryEntry.instance_id == instance_id,
                AgentMemoryEntry.tenant_id == tenant_id,
                AgentMemoryEntry.namespace == namespace,
                AgentMemoryEntry.embedding.isnot(None),
                or_(AgentMemoryEntry.expires_at.is_(None), AgentMemoryEntry.expires_at > datetime.now(UTC)),
            )
            .limit(_MAX_EMBEDDING_CANDIDATES)
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
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
