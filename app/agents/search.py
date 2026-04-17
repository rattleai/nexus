"""Unified hybrid search engine for RAG retrieval.

Combines pgvector cosine similarity with PostgreSQL full-text search
using Reciprocal Rank Fusion (RRF). Searches across both
DataSourceChunks and AgentMemoryEntries with tenant-scoped isolation.

SQL Safety: All filter clauses use parameterized queries via SQLAlchemy
text() bindings. The WHERE clause is assembled from a fixed set of
known-safe SQL fragments — no user input is interpolated into SQL.
"""

from __future__ import annotations

import contextlib
import enum
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embedding_gateway import (
    EmbeddingGatewayError,
    embedding_gateway,
    embedding_to_vector_str,
)
from app.ai.metrics import (
    RAG_CHUNKS_PER_QUERY,
    RAG_RETRIEVAL_EMPTY_TOTAL,
    RAG_RETRIEVAL_LATENCY_SECONDS,
    RAG_RETRIEVAL_TOTAL,
    RAG_TOP_SCORE,
)
from app.config import settings
from app.core.query_utils import escape_like
from app.db.models.datasource import VectorPrecision

logger = structlog.stdlib.get_logger()

# OpenTelemetry tracing — no-op when OTEL is unavailable
try:
    from opentelemetry import trace
    _rag_tracer = trace.get_tracer("app.agents.search")
except ImportError:
    _rag_tracer = None


def _rag_span(name: str, **attributes: Any) -> contextlib.AbstractContextManager:
    """Create an OTel span for RAG pipeline stages, or no-op if disabled."""
    if _rag_tracer:
        return _rag_tracer.start_as_current_span(name, attributes=attributes)
    return contextlib.nullcontext()


# Standard RRF constant (from the original RRF paper)
RRF_K = 60

# Exception types that indicate transient/expected embedding failures
# (network errors, validation errors, gateway errors). Catching these
# allows fallback to text-only search; other exceptions propagate.
_EMBEDDING_FAILURE_TYPES = (
    httpx.RequestError,
    httpx.HTTPStatusError,
    TimeoutError,
    ValueError,
    EmbeddingGatewayError,
)


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


def _use_diskann() -> bool:
    """Whether DiskANN index type is active (uses embedding_vec directly with SBQ)."""
    return settings.VECTOR_INDEX_TYPE == "diskann"


def _vec_column() -> str:
    """Column name for vector search.

    DiskANN uses embedding_vec directly (SBQ built into the index).
    HNSW switches to halfvec for 50% storage savings when configured.
    """
    if _use_diskann():
        return "embedding_vec"
    if settings.VECTOR_QUANTIZATION == VectorPrecision.HALF:
        return "embedding_halfvec"
    return "embedding_vec"


def _vec_cast() -> str:
    """SQL cast suffix matching the column type from _vec_column()."""
    if _use_diskann():
        return "::vector"
    if settings.VECTOR_QUANTIZATION == VectorPrecision.HALF:
        return "::halfvec(1536)"
    return "::vector"


# ── Known-safe SQL filter fragments ──────────────────────────
# Each entry maps a filter name to a fixed SQL clause. Only these
# are ever appended to WHERE clauses — no user input is interpolated.
_FILTER_SQL = {
    "data_source_ids": "dsc.data_source_id = ANY(:data_source_ids)",
    "source_types": "dsc.content_type = ANY(:source_types)",
    "tags": "dsc.tags ?| :tags",
    "date_from": "dsc.indexed_at >= :date_from",
    "date_to": "dsc.indexed_at <= :date_to",
    "section_title": "dsc.section_title ILIKE :section_title ESCAPE '\\'",
}


async def _apply_vector_search_settings(db: AsyncSession) -> None:
    """Apply pgvector/DiskANN query-time settings within the current transaction.

    Must be called before executing vector similarity queries. Uses SET LOCAL
    so settings are scoped to the current transaction and cannot leak to other
    sessions — safe with PgBouncer transaction-mode pooling.

    Config values (HNSW_EF_SEARCH, DISKANN_QUERY_SEARCH_LIST_SIZE) are cast
    to int before interpolation to prevent SQL injection via settings.

    Version compatibility:
      * hnsw.ef_search and diskann.query_search_list_size are required for
        their respective index types; failure to set them is a configuration
        error that should propagate.
      * hnsw.iterative_scan is newer (pgvector >=0.8.0) and is gracefully
        skipped via SAVEPOINT rollback when the GUC is unrecognized. This
        isolation prevents a version mismatch from poisoning the transaction.
    """
    if _use_diskann():
        await db.execute(
            text(
                f"SET LOCAL diskann.query_search_list_size = "
                f"{int(settings.DISKANN_QUERY_SEARCH_LIST_SIZE)}"
            )
        )
        return

    # HNSW path — ef_search tunes candidates evaluated per query (default 40
    # is too low for 1536-dim vectors; 100 provides meaningfully better recall).
    # Stable since pgvector 0.5.0 — no exception handling needed.
    await db.execute(
        text(f"SET LOCAL hnsw.ef_search = {int(settings.HNSW_EF_SEARCH)}")
    )

    # iterative_scan (pgvector >=0.8.0): re-enters the index when filtered
    # candidates are exhausted, preventing under-fetching on selective WHERE
    # clauses. Up to 9x improvement on filtered queries. Wrapped in an explicit
    # SAVEPOINT so a failed SET (on older pgvector) doesn't abort the outer
    # transaction. Uses raw SAVEPOINT SQL rather than session.begin_nested()
    # so it routes through db.execute() uniformly.
    if settings.PGVECTOR_ITERATIVE_SCAN:
        await db.execute(text("SAVEPOINT vector_settings_sp"))
        try:
            await db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            await db.execute(text("RELEASE SAVEPOINT vector_settings_sp"))
        except Exception:
            # pgvector <0.8.0 does not support iterative_scan — roll back
            # the savepoint so the outer transaction remains usable.
            try:
                await db.execute(text("ROLLBACK TO SAVEPOINT vector_settings_sp"))
                await db.execute(text("RELEASE SAVEPOINT vector_settings_sp"))
            except Exception:
                pass
            logger.debug("hnsw_iterative_scan_set_failed", exc_info=True)


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
        # Over-fetch factor of 3x for RRF merging: ensures enough candidates
        # from each search mode to produce quality fused results.
        over_fetch = limit * 3

        # Validate weights
        if vector_weight + text_weight <= 0:
            vector_weight, text_weight = 0.6, 0.4

        start = time.monotonic()

        results: list[SearchResult] = []

        if search_type in (SearchType.VECTOR, SearchType.HYBRID):
            with _rag_span("rag.embed_query"):
                query_embedding = await self._get_query_embedding(query)
            if query_embedding is None and search_type == SearchType.VECTOR:
                return []
        else:
            query_embedding = None

        # Chunks and memory searches share the same AsyncSession, which is
        # NOT safe for concurrent use — run them sequentially.
        if SearchSource.CHUNKS in sources:
            with _rag_span("rag.search_chunks", search_type=search_type.value):
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
            with _rag_span("rag.search_memory"):
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

        # Resolve parent chunks when parent-child retrieval is enabled
        if settings.RAG_PARENT_CHILD_ENABLED and results:
            with _rag_span("rag.parent_child_resolve"):
                results = await self._resolve_parent_chunks(results, tenant_id, db)

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

        if elapsed > 1.0:
            logger.warning(
                "slow_search_query",
                search_type=search_type.value,
                latency_ms=int(elapsed * 1000),
                results=len(results),
            )
        else:
            logger.info(
                "hybrid_search_completed",
                search_type=search_type.value,
                sources=[s.value for s in sources],
                results=len(results),
                latency_ms=int(elapsed * 1000),
            )
        return results

    async def _resolve_parent_chunks(
        self,
        results: list[SearchResult],
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> list[SearchResult]:
        """Replace child chunk results with their parent chunks for richer context.

        Child chunks matched during vector search are resolved to their parent
        chunks. Deduplicates parents that multiple children point to. All
        queries are tenant-scoped to prevent cross-tenant content disclosure.
        """
        child_ids = [
            r.id for r in results
            if r.source == SearchSource.CHUNKS
        ]
        if not child_ids:
            return results

        # Query for parent_chunk_id mapping (tenant-scoped)
        sql = """
            SELECT id::text, parent_chunk_id::text, chunk_level
            FROM data_source_chunks
            WHERE id = ANY(:chunk_ids)
              AND tenant_id = :tenant_id
              AND deleted_at IS NULL
              AND parent_chunk_id IS NOT NULL
        """
        result = await db.execute(
            text(sql),
            {"chunk_ids": child_ids, "tenant_id": str(tenant_id)},
        )
        child_to_parent = {
            row["id"]: row["parent_chunk_id"]
            for row in result.mappings().all()
        }

        if not child_to_parent:
            return results

        # Fetch parent chunk content (tenant-scoped)
        parent_ids = list(set(child_to_parent.values()))
        parent_sql = """
            SELECT id::text, content, data_source_id::text, section_title, content_type
            FROM data_source_chunks
            WHERE id = ANY(:parent_ids)
              AND tenant_id = :tenant_id
              AND deleted_at IS NULL
        """
        parent_result = await db.execute(
            text(parent_sql),
            {"parent_ids": parent_ids, "tenant_id": str(tenant_id)},
        )
        parents = {row["id"]: row for row in parent_result.mappings().all()}

        # Replace child results with parent content, keeping child's score
        resolved = []
        seen_parents: set[str] = set()
        for r in results:
            parent_id = child_to_parent.get(r.id)
            if parent_id and parent_id in parents and parent_id not in seen_parents:
                parent = parents[parent_id]
                resolved.append(SearchResult(
                    id=parent_id,
                    content=parent["content"] or "",
                    score=r.score,
                    source=r.source,
                    source_id=str(parent["data_source_id"]) if parent["data_source_id"] else "",
                    metadata={
                        **r.metadata,
                        "resolved_from_child": r.id,
                        "section_title": parent["section_title"],
                        "content_type": parent["content_type"],
                    },
                    search_type=r.search_type,
                ))
                seen_parents.add(parent_id)
            elif parent_id and parent_id in seen_parents:
                continue  # Skip duplicate parent
            else:
                resolved.append(r)

        return resolved

    async def _get_query_embedding(self, query: str) -> list[float] | None:
        """Generate embedding for the query. Returns None on transient failure."""
        try:
            return await embedding_gateway.generate(query)
        except _EMBEDDING_FAILURE_TYPES as exc:
            logger.warning("search_query_embedding_failed", error=type(exc).__name__, exc_info=True)
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
        # Apply vector index tuning (ef_search, iterative_scan, DiskANN search list)
        if query_embedding is not None:
            await _apply_vector_search_settings(db)

        params: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "limit": limit,
            "query": query,
        }

        # Build filter clauses from the fixed-safe SQL fragments
        filter_clauses = ["dsc.tenant_id = :tenant_id", "dsc.deleted_at IS NULL"]
        if filters.data_source_ids:
            filter_clauses.append(_FILTER_SQL["data_source_ids"])
            params["data_source_ids"] = [str(d) for d in filters.data_source_ids]
        if filters.source_types:
            filter_clauses.append(_FILTER_SQL["source_types"])
            params["source_types"] = filters.source_types
        if filters.tags:
            filter_clauses.append(_FILTER_SQL["tags"])
            params["tags"] = filters.tags
        if filters.date_from:
            filter_clauses.append(_FILTER_SQL["date_from"])
            params["date_from"] = filters.date_from
        if filters.date_to:
            filter_clauses.append(_FILTER_SQL["date_to"])
            params["date_to"] = filters.date_to
        if filters.section_title:
            filter_clauses.append(_FILTER_SQL["section_title"])
            params["section_title"] = f"%{escape_like(filters.section_title)}%"

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
        params["query_vec"] = embedding_to_vector_str(query_embedding)
        params["vec_w"] = vector_weight
        params["text_w"] = text_weight

        col = _vec_column()
        cast = _vec_cast()

        sql = f"""
            WITH vector_results AS (
                SELECT dsc.id, dsc.content, dsc.data_source_id, dsc.section_title,
                       dsc.content_type,
                       1 - (dsc.{col} <=> :query_vec{cast}) AS vec_score,
                       ROW_NUMBER() OVER (ORDER BY dsc.{col} <=> :query_vec{cast}) AS vec_rank
                FROM data_source_chunks dsc
                WHERE {where} AND dsc.{col} IS NOT NULL
                ORDER BY dsc.{col} <=> :query_vec{cast}
                LIMIT :limit
            ),
            text_results AS (
                SELECT dsc.id, dsc.content, dsc.data_source_id, dsc.section_title,
                       dsc.content_type,
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
                content=row["content"] or "",
                score=float(row["rrf_score"] or 0),
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
        params["query_vec"] = embedding_to_vector_str(query_embedding)

        col = _vec_column()
        cast = _vec_cast()

        sql = f"""
            SELECT dsc.id, dsc.content, dsc.data_source_id, dsc.section_title,
                   dsc.content_type,
                   1 - (dsc.{col} <=> :query_vec{cast}) AS score
            FROM data_source_chunks dsc
            WHERE {where} AND dsc.{col} IS NOT NULL
            ORDER BY dsc.{col} <=> :query_vec{cast}
            LIMIT :limit
        """

        result = await db.execute(text(sql), params)
        rows = result.mappings().all()

        return [
            SearchResult(
                id=str(row["id"]),
                content=row["content"] or "",
                score=float(row["score"] or 0),
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
                content=row["content"] or "",
                score=float(row["score"] or 0),
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

        await _apply_vector_search_settings(db)

        vector_str = embedding_to_vector_str(query_embedding)

        col = _vec_column()
        cast = _vec_cast()

        sql = f"""
            SELECT key, value, namespace,
                   1 - ({col} <=> :query_vec{cast}) AS score
            FROM agent_memory_entries
            WHERE tenant_id = :tenant_id
              AND namespace = :namespace
              AND {col} IS NOT NULL
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY {col} <=> :query_vec{cast}
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

        search_results = []
        for row in rows:
            val = row["value"]
            if isinstance(val, dict):
                content = val.get("text", "")
                source_ref = val.get("source", "")
            elif isinstance(val, str):
                content = val
                source_ref = ""
            else:
                content = str(val)[:1000] if val is not None else ""
                source_ref = ""

            search_results.append(SearchResult(
                id=row["key"],
                content=content,
                score=float(row["score"] or 0),
                source=SearchSource.MEMORY,
                metadata={
                    "namespace": row["namespace"],
                    "source": source_ref,
                },
                search_type=SearchType.VECTOR,
            ))
        return search_results


# Module-level singleton
hybrid_search_engine = HybridSearchEngine()
