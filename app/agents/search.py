"""Unified hybrid search engine for RAG retrieval.

Combines pgvector cosine similarity with PostgreSQL full-text search
using Reciprocal Rank Fusion (RRF). Searches across both
DataSourceChunks and AgentMemoryEntries with tenant-scoped isolation.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.metrics import (
    RAG_CHUNKS_PER_QUERY,
    RAG_RETRIEVAL_EMPTY_TOTAL,
    RAG_RETRIEVAL_LATENCY_SECONDS,
    RAG_RETRIEVAL_TOTAL,
    RAG_TOP_SCORE,
)
from app.config import settings

logger = structlog.stdlib.get_logger()

# Standard RRF constant (from the original RRF paper)
RRF_K = 60


class SearchType(enum.StrEnum):
    VECTOR = "vector"
    TEXT = "text"
    HYBRID = "hybrid"


class SearchSource(enum.StrEnum):
    CHUNKS = "chunks"
    MEMORY = "memory"


@dataclass
class SearchFilters:
    """Filters for narrowing vector search results."""

    data_source_ids: list[uuid.UUID] | None = None
    source_types: list[str] | None = None
    tags: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    section_title: str | None = None
    namespace: str = "rag"


@dataclass
class SearchResult:
    """A single search result."""

    id: str
    content: str
    score: float
    source: SearchSource
    source_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    search_type: SearchType = SearchType.HYBRID


class HybridSearchEngine:
    """Hybrid search combining vector similarity and full-text search with RRF."""

    async def search(
        self,
        query: str,
        tenant_id: uuid.UUID,
        *,
        sources: list[SearchSource] | None = None,
        filters: SearchFilters | None = None,
        limit: int = 10,
        search_type: SearchType = SearchType.HYBRID,
        vector_weight: float = 0.6,
        text_weight: float = 0.4,
        db: AsyncSession,
    ) -> list[SearchResult]:
        """Execute a hybrid search across specified sources.

        Args:
            query: Search query text.
            tenant_id: Tenant ID for RLS scoping.
            sources: Which tables to search (chunks, memory, or both).
            filters: Optional metadata filters.
            limit: Maximum results to return.
            search_type: vector, text, or hybrid.
            vector_weight: Weight for vector search in RRF (0-1).
            text_weight: Weight for text search in RRF (0-1).
            db: Async database session.

        Returns:
            List of SearchResult sorted by relevance.
        """
        sources = sources or [SearchSource.CHUNKS, SearchSource.MEMORY]
        filters = filters or SearchFilters()
        limit = min(limit, 50)
        over_fetch = limit * 3  # Over-fetch for RRF merging

        start = time.monotonic()

        results: list[SearchResult] = []

        if search_type == SearchType.VECTOR or search_type == SearchType.HYBRID:
            # Generate query embedding
            query_embedding = await self._get_query_embedding(query)
            if query_embedding is None and search_type == SearchType.VECTOR:
                return []
        else:
            query_embedding = None

        # Search each source
        if SearchSource.CHUNKS in sources:
            chunk_results = await self._search_chunks(
                query=query,
                query_embedding=query_embedding,
                tenant_id=tenant_id,
                filters=filters,
                limit=over_fetch,
                search_type=search_type,
                vector_weight=vector_weight,
                text_weight=text_weight,
                db=db,
            )
            results.extend(chunk_results)

        if SearchSource.MEMORY in sources:
            memory_results = await self._search_memory(
                query=query,
                query_embedding=query_embedding,
                tenant_id=tenant_id,
                filters=filters,
                limit=over_fetch,
                search_type=search_type,
                db=db,
            )
            results.extend(memory_results)

        # Sort by score and trim
        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:limit]

        elapsed = time.monotonic() - start

        # Record metrics
        RAG_RETRIEVAL_TOTAL.labels(search_type=search_type.value).inc()
        RAG_RETRIEVAL_LATENCY_SECONDS.labels(search_type=search_type.value).observe(elapsed)
        RAG_CHUNKS_PER_QUERY.labels(search_type=search_type.value).observe(len(results))
        if results:
            RAG_TOP_SCORE.labels(search_type=search_type.value).observe(results[0].score)
        else:
            RAG_RETRIEVAL_EMPTY_TOTAL.labels(search_type=search_type.value).inc()

        logger.info(
            "hybrid_search_completed",
            search_type=search_type.value,
            sources=[s.value for s in sources],
            results=len(results),
            latency_ms=int(elapsed * 1000),
        )
        return results

    async def _get_query_embedding(self, query: str) -> list[float] | None:
        """Generate embedding for the query."""
        try:
            from app.ai.embedding_gateway import embedding_gateway

            return await embedding_gateway.generate(query)
        except Exception:
            logger.warning("search_query_embedding_failed", exc_info=True)
            return None

    async def _search_chunks(
        self,
        *,
        query: str,
        query_embedding: list[float] | None,
        tenant_id: uuid.UUID,
        filters: SearchFilters,
        limit: int,
        search_type: SearchType,
        vector_weight: float,
        text_weight: float,
        db: AsyncSession,
    ) -> list[SearchResult]:
        """Search data_source_chunks with hybrid or single-mode search."""
        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "limit": limit,
            "query": query,
        }

        # Build filter clauses
        filter_clauses = ["dsc.tenant_id = :tenant_id"]
        if filters.data_source_ids:
            filter_clauses.append("dsc.data_source_id = ANY(:data_source_ids)")
            params["data_source_ids"] = [str(d) for d in filters.data_source_ids]
        if filters.source_types:
            filter_clauses.append("dsc.content_type = ANY(:source_types)")
            params["source_types"] = filters.source_types
        if filters.tags:
            filter_clauses.append("dsc.tags ?| :tags")
            params["tags"] = filters.tags
        if filters.date_from:
            filter_clauses.append("dsc.indexed_at >= :date_from")
            params["date_from"] = filters.date_from
        if filters.date_to:
            filter_clauses.append("dsc.indexed_at <= :date_to")
            params["date_to"] = filters.date_to
        if filters.section_title:
            filter_clauses.append("dsc.section_title ILIKE :section_title")
            params["section_title"] = f"%{filters.section_title}%"

        where = " AND ".join(filter_clauses)

        if search_type == SearchType.HYBRID and query_embedding is not None:
            return await self._hybrid_chunk_search(
                query_embedding, query, where, params, limit,
                vector_weight, text_weight, db,
            )
        elif search_type == SearchType.VECTOR and query_embedding is not None:
            return await self._vector_chunk_search(
                query_embedding, where, params, limit, db,
            )
        elif search_type == SearchType.TEXT:
            return await self._text_chunk_search(query, where, params, limit, db)
        elif query_embedding is not None:
            # Hybrid requested but fallback to vector-only
            return await self._vector_chunk_search(
                query_embedding, where, params, limit, db,
            )
        else:
            return await self._text_chunk_search(query, where, params, limit, db)

    async def _hybrid_chunk_search(
        self,
        query_embedding: list[float],
        query: str,
        where: str,
        params: dict,
        limit: int,
        vector_weight: float,
        text_weight: float,
        db: AsyncSession,
    ) -> list[SearchResult]:
        """Combined vector + full-text search with RRF scoring."""
        vector_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
        params["query_vec"] = vector_str
        params["vec_w"] = vector_weight
        params["text_w"] = text_weight

        sql = f"""
            WITH vector_results AS (
                SELECT dsc.id, dsc.content, dsc.data_source_id, dsc.section_title,
                       dsc.content_type, dsc.tags,
                       1 - (dsc.embedding_vec <=> :query_vec::vector) AS vec_score,
                       ROW_NUMBER() OVER (ORDER BY dsc.embedding_vec <=> :query_vec::vector) AS vec_rank
                FROM data_source_chunks dsc
                WHERE {where} AND dsc.embedding_vec IS NOT NULL
                ORDER BY dsc.embedding_vec <=> :query_vec::vector
                LIMIT :limit
            ),
            text_results AS (
                SELECT dsc.id, dsc.content, dsc.data_source_id, dsc.section_title,
                       dsc.content_type, dsc.tags,
                       ts_rank_cd(dsc.content_tsv, plainto_tsquery('english', :query)) AS text_score,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank_cd(dsc.content_tsv, plainto_tsquery('english', :query)) DESC
                       ) AS text_rank
                FROM data_source_chunks dsc
                WHERE {where} AND dsc.content_tsv @@ plainto_tsquery('english', :query)
                ORDER BY text_score DESC
                LIMIT :limit
            )
            SELECT COALESCE(v.id, t.id) AS id,
                   COALESCE(v.content, t.content) AS content,
                   COALESCE(v.data_source_id, t.data_source_id) AS data_source_id,
                   COALESCE(v.section_title, t.section_title) AS section_title,
                   COALESCE(v.content_type, t.content_type) AS content_type,
                   (COALESCE(:vec_w / ({RRF_K} + v.vec_rank), 0) +
                    COALESCE(:text_w / ({RRF_K} + t.text_rank), 0)) AS rrf_score,
                   v.vec_score,
                   t.text_score
            FROM vector_results v
            FULL OUTER JOIN text_results t ON v.id = t.id
            ORDER BY rrf_score DESC
            LIMIT :limit
        """

        result = await db.execute(text(sql), params)
        rows = result.mappings().all()

        return [
            SearchResult(
                id=str(row["id"]),
                content=row["content"],
                score=float(row["rrf_score"]),
                source=SearchSource.CHUNKS,
                source_id=str(row["data_source_id"]) if row["data_source_id"] else "",
                metadata={
                    "section_title": row["section_title"],
                    "content_type": row["content_type"],
                    "vec_score": float(row["vec_score"]) if row["vec_score"] is not None else None,
                    "text_score": float(row["text_score"]) if row["text_score"] is not None else None,
                },
                search_type=SearchType.HYBRID,
            )
            for row in rows
        ]

    async def _vector_chunk_search(
        self,
        query_embedding: list[float],
        where: str,
        params: dict,
        limit: int,
        db: AsyncSession,
    ) -> list[SearchResult]:
        """Pure vector similarity search on chunks."""
        vector_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
        params["query_vec"] = vector_str

        sql = f"""
            SELECT dsc.id, dsc.content, dsc.data_source_id, dsc.section_title,
                   dsc.content_type,
                   1 - (dsc.embedding_vec <=> :query_vec::vector) AS score
            FROM data_source_chunks dsc
            WHERE {where} AND dsc.embedding_vec IS NOT NULL
            ORDER BY dsc.embedding_vec <=> :query_vec::vector
            LIMIT :limit
        """

        result = await db.execute(text(sql), params)
        rows = result.mappings().all()

        return [
            SearchResult(
                id=str(row["id"]),
                content=row["content"],
                score=float(row["score"]),
                source=SearchSource.CHUNKS,
                source_id=str(row["data_source_id"]) if row["data_source_id"] else "",
                metadata={
                    "section_title": row["section_title"],
                    "content_type": row["content_type"],
                },
                search_type=SearchType.VECTOR,
            )
            for row in rows
        ]

    async def _text_chunk_search(
        self,
        query: str,
        where: str,
        params: dict,
        limit: int,
        db: AsyncSession,
    ) -> list[SearchResult]:
        """Pure full-text search on chunks."""
        sql = f"""
            SELECT dsc.id, dsc.content, dsc.data_source_id, dsc.section_title,
                   dsc.content_type,
                   ts_rank_cd(dsc.content_tsv, plainto_tsquery('english', :query)) AS score
            FROM data_source_chunks dsc
            WHERE {where} AND dsc.content_tsv @@ plainto_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT :limit
        """

        result = await db.execute(text(sql), params)
        rows = result.mappings().all()

        return [
            SearchResult(
                id=str(row["id"]),
                content=row["content"],
                score=float(row["score"]),
                source=SearchSource.CHUNKS,
                source_id=str(row["data_source_id"]) if row["data_source_id"] else "",
                metadata={
                    "section_title": row["section_title"],
                    "content_type": row["content_type"],
                },
                search_type=SearchType.TEXT,
            )
            for row in rows
        ]

    async def _search_memory(
        self,
        *,
        query: str,
        query_embedding: list[float] | None,
        tenant_id: uuid.UUID,
        filters: SearchFilters,
        limit: int,
        search_type: SearchType,
        db: AsyncSession,
    ) -> list[SearchResult]:
        """Search agent_memory_entries for RAG content."""
        if query_embedding is None:
            return []

        if not settings.AGENT_MEMORY_VECTOR_ENABLED:
            return []

        vector_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        sql = """
            SELECT key, value, namespace,
                   1 - (embedding_vec <=> :query_vec::vector) AS score
            FROM agent_memory_entries
            WHERE tenant_id = :tenant_id
              AND namespace = :namespace
              AND embedding_vec IS NOT NULL
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY embedding_vec <=> :query_vec::vector
            LIMIT :limit
        """

        result = await db.execute(
            text(sql),
            {
                "query_vec": vector_str,
                "tenant_id": str(tenant_id),
                "namespace": filters.namespace,
                "limit": limit,
            },
        )
        rows = result.mappings().all()

        return [
            SearchResult(
                id=row["key"],
                content=row["value"].get("text", "") if isinstance(row["value"], dict) else str(row["value"]),
                score=float(row["score"]),
                source=SearchSource.MEMORY,
                metadata={
                    "namespace": row["namespace"],
                    "source": row["value"].get("source", "") if isinstance(row["value"], dict) else "",
                },
                search_type=SearchType.VECTOR,
            )
            for row in rows
        ]


# Module-level singleton
hybrid_search_engine = HybridSearchEngine()
