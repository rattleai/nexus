"""Unified search API endpoint for RAG retrieval.

Provides a single endpoint that searches across DataSourceChunks
and AgentMemoryEntries using hybrid (vector + full-text) search
with optional re-ranking.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.reranker import reranker
from app.agents.search import (
    HybridSearchEngine,
    SearchFilters,
    SearchResult,
    SearchSource,
    SearchType,
    hybrid_search_engine,
)
from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.db.session import set_tenant_context

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/search", tags=["search"])


# ── Request / Response schemas ───────────────────────────────


class SearchFilterRequest(BaseModel):
    data_source_ids: list[uuid.UUID] | None = None
    source_types: list[str] | None = None
    tags: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    section_title: str | None = None
    namespace: str = "rag"


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    sources: list[str] | None = Field(
        default=None, description="Sources to search: 'chunks', 'memory'"
    )
    filters: SearchFilterRequest | None = None
    limit: int = Field(default=10, ge=1, le=50)
    search_type: str = Field(default="hybrid", description="vector, text, or hybrid")
    rerank: bool = Field(default=False, description="Apply re-ranking to results")
    vector_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    text_weight: float = Field(default=0.4, ge=0.0, le=1.0)


class SearchResultResponse(BaseModel):
    id: str
    content: str
    score: float
    source_type: str
    source_id: str = ""
    metadata: dict[str, Any] = {}


class SearchResponse(BaseModel):
    results: list[SearchResultResponse]
    metrics: dict[str, Any]


# ── Endpoint ─────────────────────────────────────────────────


@router.post(
    "",
    response_model=SearchResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def search(
    request: SearchRequest,
    tenant=Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Search across documents and agent memory using hybrid search.

    Combines vector similarity (pgvector) with full-text search (tsvector)
    using Reciprocal Rank Fusion. Optionally re-ranks results for precision.
    """
    await set_tenant_context(db, str(tenant.id))

    start = time.monotonic()

    # Parse sources
    sources: list[SearchSource] = []
    if request.sources:
        for s in request.sources:
            try:
                sources.append(SearchSource(s))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid source: {s}. Must be 'chunks' or 'memory'.",
                )
    else:
        sources = [SearchSource.CHUNKS, SearchSource.MEMORY]

    # Parse search type
    try:
        search_type = SearchType(request.search_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid search_type: {request.search_type}. Must be 'vector', 'text', or 'hybrid'.",
        )

    # Build filters
    filters = SearchFilters()
    if request.filters:
        f = request.filters
        filters.data_source_ids = f.data_source_ids
        filters.source_types = f.source_types
        filters.tags = f.tags
        filters.section_title = f.section_title
        filters.namespace = f.namespace
        if f.date_from:
            from datetime import datetime as dt, timezone

            try:
                parsed = dt.fromisoformat(f.date_from)
                filters.date_from = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid date_from format: {f.date_from}")
        if f.date_to:
            from datetime import datetime as dt, timezone

            try:
                parsed = dt.fromisoformat(f.date_to)
                filters.date_to = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid date_to format: {f.date_to}")

    # Determine limit (over-fetch if reranking)
    fetch_limit = request.limit * 3 if request.rerank else request.limit

    # Execute search
    try:
        results = await hybrid_search_engine.search(
            query=request.query,
            tenant_id=tenant.id,
            sources=sources,
            filters=filters,
            limit=fetch_limit,
            search_type=search_type,
            vector_weight=request.vector_weight,
            text_weight=request.text_weight,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("search_failed", error=type(exc).__name__, exc_info=True)
        raise HTTPException(status_code=500, detail="Search operation failed")

    # Apply re-ranking if requested
    reranked = False
    if request.rerank and results:
        documents = [r.content for r in results]
        rerank_results = await reranker.rerank(
            query=request.query,
            documents=documents,
            top_k=request.limit,
        )
        # Rebuild results in reranked order
        reranked_results = []
        for rr in rerank_results:
            if rr.index < len(results):
                original = results[rr.index]
                reranked_results.append(SearchResult(
                    id=original.id,
                    content=original.content,
                    score=rr.score,
                    source=original.source,
                    source_id=original.source_id,
                    metadata=original.metadata,
                    search_type=original.search_type,
                ))
        results = reranked_results
        reranked = True
    else:
        results = results[:request.limit]

    elapsed = time.monotonic() - start

    return SearchResponse(
        results=[
            SearchResultResponse(
                id=r.id,
                content=r.content,
                score=r.score,
                source_type=r.source.value,
                source_id=r.source_id,
                metadata=r.metadata,
            )
            for r in results
        ],
        metrics={
            "latency_ms": int(elapsed * 1000),
            "total_candidates": fetch_limit,
            "returned": len(results),
            "search_type": search_type.value,
            "reranked": reranked,
            "sources": [s.value for s in sources],
        },
    )
