"""Semantic query cache: cache search results keyed by query similarity.

Avoids redundant embedding + search + reranking cycles for semantically
similar queries. Uses Matryoshka truncation (first 64 dims) for fast
cache matching and Redis for storage.

Cache is per-tenant with configurable TTL and similarity threshold.
"""

from __future__ import annotations

import hashlib
import json
import math
import time

import structlog

from app.config import settings
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Number of embedding dimensions to use for cache key matching
# (Matryoshka truncation — first N dims preserve semantic quality)
_CACHE_DIMS = 64


def _truncate_embedding(embedding: list[float], dims: int = _CACHE_DIMS) -> list[float]:
    """Truncate embedding to first N dimensions for fast cache matching."""
    return embedding[:dims]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _embedding_hash(embedding: list[float]) -> str:
    """Hash a truncated embedding for Redis key generation."""
    raw = json.dumps(embedding, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class SemanticQueryCache:
    """Cache search results by semantic similarity to the query embedding."""

    async def get(
        self,
        query_embedding: list[float],
        tenant_id: str,
    ) -> list[dict] | None:
        """Check cache for a semantically similar query.

        Returns cached results if a similar query was found, None otherwise.
        """
        if not settings.RAG_QUERY_CACHE_ENABLED or not query_embedding:
            return None

        truncated = _truncate_embedding(query_embedding)
        threshold = settings.RAG_QUERY_CACHE_SIMILARITY_THRESHOLD

        try:
            # Get recent cached query embeddings for this tenant
            cache_key = f"rag:qcache:{tenant_id}:index"
            cached_entries = await redis_pool.zrevrangebyscore(
                cache_key,
                max="+inf",
                min="-inf",
                start=0,
                num=50,  # Check at most 50 recent queries
            )

            for entry_bytes in cached_entries:
                entry = json.loads(entry_bytes)
                cached_emb = entry.get("emb", [])
                if not cached_emb:
                    continue

                sim = _cosine_similarity(truncated, cached_emb)
                if sim >= threshold:
                    # Cache hit — fetch the stored results
                    result_key = f"rag:qcache:{tenant_id}:results:{entry['hash']}"
                    raw_results = await redis_pool.get(result_key)
                    if raw_results:
                        logger.info(
                            "query_cache_hit",
                            tenant_id=tenant_id,
                            similarity=round(sim, 3),
                        )
                        return json.loads(raw_results)

            return None

        except Exception:
            logger.debug("query_cache_get_failed", exc_info=True)
            return None

    async def set(
        self,
        query_embedding: list[float],
        tenant_id: str,
        results: list[dict],
    ) -> None:
        """Cache search results for a query embedding."""
        if not settings.RAG_QUERY_CACHE_ENABLED or not query_embedding:
            return

        truncated = _truncate_embedding(query_embedding)
        emb_hash = _embedding_hash(truncated)
        ttl = settings.RAG_QUERY_CACHE_TTL_SECONDS

        try:
            # Store the query embedding in the tenant's sorted set (score = timestamp)
            cache_key = f"rag:qcache:{tenant_id}:index"
            entry = json.dumps({"emb": truncated, "hash": emb_hash})
            await redis_pool.zadd(cache_key, {entry: time.time()})
            await redis_pool.expire(cache_key, ttl * 2)  # Index lives longer than individual results

            # Store the results
            result_key = f"rag:qcache:{tenant_id}:results:{emb_hash}"
            await redis_pool.set(result_key, json.dumps(results), ex=ttl)

            # Trim old entries (keep at most 200 per tenant)
            await redis_pool.zremrangebyrank(cache_key, 0, -201)

        except Exception:
            logger.debug("query_cache_set_failed", exc_info=True)

    async def invalidate(self, tenant_id: str) -> None:
        """Invalidate all cached queries for a tenant."""
        try:
            cache_key = f"rag:qcache:{tenant_id}:index"
            entries = await redis_pool.zrangebyscore(cache_key, "-inf", "+inf")
            keys_to_delete = [cache_key]
            for entry_bytes in entries:
                entry = json.loads(entry_bytes)
                keys_to_delete.append(f"rag:qcache:{tenant_id}:results:{entry.get('hash', '')}")
            if keys_to_delete:
                await redis_pool.delete(*keys_to_delete)
        except Exception:
            logger.debug("query_cache_invalidate_failed", exc_info=True)


# Module-level singleton
semantic_query_cache = SemanticQueryCache()
