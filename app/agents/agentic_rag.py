"""Agentic RAG: multi-step retrieval with self-critique and iterative refinement.

Single-pass retrieval often misses relevant context. Agentic RAG performs
multi-step retrieval:
  1. Initial retrieval (standard hybrid search)
  2. Self-critique: LLM assesses whether results are sufficient
  3. If insufficient: reformulate query, retrieve again
  4. Merge and deduplicate results across iterations
  5. Final re-ranking

Max iterations capped at RAG_AGENTIC_MAX_ITERATIONS (default 3).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.query_router import QueryPlan, query_router
from app.agents.reranker import reranker
from app.agents.search import (
    HybridSearchEngine,
    SearchFilters,
    SearchResult,
    SearchType,
    hybrid_search_engine,
)
from app.config import settings

logger = structlog.stdlib.get_logger()


def _safe_search_type(plan: QueryPlan | None) -> SearchType:
    """Resolve a QueryPlan's search_type string to a SearchType enum.

    Defaults to HYBRID when the plan is missing or contains an unrecognized
    string (plans may come from external sources — API input, cached state —
    where arbitrary values could appear).
    """
    if plan is None:
        return SearchType.HYBRID
    try:
        return SearchType(plan.search_type)
    except ValueError:
        logger.warning("invalid_plan_search_type", value=plan.search_type)
        return SearchType.HYBRID


class AgenticRAGPipeline:
    """Multi-step retrieval with self-critique and iterative refinement."""

    def __init__(self, search_engine: HybridSearchEngine | None = None):
        self._search = search_engine or hybrid_search_engine

    async def retrieve(
        self,
        query: str,
        tenant_id: uuid.UUID,
        *,
        db: AsyncSession,
        filters: SearchFilters | None = None,
        limit: int = 10,
        plan: QueryPlan | None = None,
    ) -> list[SearchResult]:
        """Execute adaptive multi-step agentic retrieval.

        When query routing is enabled, the QueryPlan controls pipeline depth:
        simple queries skip re-ranking/HyDE/agentic steps, complex queries
        get the full treatment.

        Returns deduplicated, re-ranked results from multiple iterations.
        """
        # Build query plan (adaptive depth)
        if plan is None and settings.RAG_QUERY_ROUTING_ENABLED:
            plan = query_router.route(query)

        if not settings.RAG_AGENTIC_ENABLED:
            search_type = _safe_search_type(plan)
            return await self._search.search(
                query=query,
                tenant_id=tenant_id,
                db=db,
                filters=filters,
                limit=limit,
                search_type=search_type,
                vector_weight=plan.vector_weight if plan else 0.6,
                text_weight=plan.text_weight if plan else 0.4,
            )

        # Adaptive iteration count: plan overrides global config
        max_iterations = plan.agentic_iterations if plan else settings.RAG_AGENTIC_MAX_ITERATIONS
        search_type = _safe_search_type(plan)
        effective_limit = int(limit * (plan.limit_multiplier if plan else 1.0))

        all_results: dict[str, SearchResult] = {}  # Dedup by chunk ID
        current_query = query

        for iteration in range(max_iterations):
            results = await self._search.search(
                query=current_query,
                tenant_id=tenant_id,
                db=db,
                filters=filters,
                limit=effective_limit * 2,  # Over-fetch for merging
                search_type=search_type,
                vector_weight=plan.vector_weight if plan else 0.6,
                text_weight=plan.text_weight if plan else 0.4,
            )

            # CRAG: grade documents and filter out irrelevant ones
            if settings.RAG_CRAG_ENABLED:
                from app.agents.corrective_rag import crag_evaluator

                crag_outcome = await crag_evaluator.evaluate(query, results)
                results = crag_outcome.kept_results

            # Merge with deduplication (keep highest score)
            for r in results:
                if r.id not in all_results or r.score > all_results[r.id].score:
                    all_results[r.id] = r

            # Self-critique: assess if results are sufficient
            if iteration < max_iterations - 1:
                is_sufficient = await self._assess_sufficiency(
                    query,
                    [r.content for r in results[:5]],
                )
                if is_sufficient:
                    logger.info(
                        "agentic_rag_sufficient",
                        query=query[:100],
                        iteration=iteration + 1,
                        total_results=len(all_results),
                    )
                    break

                # Reformulate query for next iteration
                reformulated = await self._reformulate_query(query, current_query, results[:5])
                if reformulated and reformulated != current_query:
                    current_query = reformulated
                    logger.info(
                        "agentic_rag_reformulated",
                        iteration=iteration + 1,
                        new_query=reformulated[:100],
                    )
                else:
                    break  # No better query to try

        # Sort merged results and trim
        final = sorted(all_results.values(), key=lambda r: r.score, reverse=True)

        # Apply re-ranking only when the plan says to (or always when no plan)
        should_rerank = settings.RAG_RERANKER_PROVIDER != "none" and final and (plan is None or plan.use_reranking)
        if should_rerank:
            documents = [r.content for r in final[: effective_limit * 2]]
            reranked = await reranker.rerank(query=query, documents=documents, top_k=effective_limit)
            reranked_results = []
            for rr in reranked:
                if rr.index < len(final):
                    original = final[rr.index]
                    reranked_results.append(
                        SearchResult(
                            id=original.id,
                            content=original.content,
                            score=rr.score,
                            source=original.source,
                            source_id=original.source_id,
                            metadata=original.metadata,
                            search_type=original.search_type,
                        )
                    )
            return reranked_results

        return final[:effective_limit]

    async def _assess_sufficiency(
        self,
        query: str,
        top_contents: list[str],
    ) -> bool:
        """Assess whether retrieved results are sufficient to answer the query."""
        try:
            from app.ai.gateway import ai_gateway

            context = "\n---\n".join(top_contents[:3])
            response = await ai_gateway.complete(
                model=settings.RAG_HYDE_MODEL,  # Cheap model
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Given these retrieved documents, can the following "
                            "question be fully answered? Reply ONLY 'yes' or 'no'.\n\n"
                            f"Question: {query}\n\n"
                            f"Documents:\n{context}"
                        ),
                    }
                ],
                max_tokens=5,
                temperature=0.0,
            )

            content = ""
            if response and hasattr(response, "content"):
                content = response.content
            elif isinstance(response, dict):
                content = response.get("content", "")

            return content.strip().lower().startswith("yes")

        except Exception:
            logger.debug("agentic_sufficiency_check_failed", exc_info=True)
            return True  # Default to sufficient on failure

    async def _reformulate_query(
        self,
        original_query: str,
        current_query: str,
        results: list[SearchResult],
    ) -> str | None:
        """Reformulate the query to find missing information."""
        try:
            from app.ai.gateway import ai_gateway

            context = "\n".join(r.content[:200] for r in results[:3])
            response = await ai_gateway.complete(
                model=settings.RAG_HYDE_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "The following search did not fully answer the question. "
                            "Reformulate the query to find the missing information. "
                            "Reply with ONLY the new search query, nothing else.\n\n"
                            f"Original question: {original_query}\n"
                            f"Current search: {current_query}\n"
                            f"Results found (partial):\n{context}"
                        ),
                    }
                ],
                max_tokens=100,
                temperature=0.0,
            )

            content = ""
            if response and hasattr(response, "content"):
                content = response.content
            elif isinstance(response, dict):
                content = response.get("content", "")

            reformulated = content.strip()
            return reformulated if reformulated else None

        except Exception:
            logger.debug("agentic_reformulation_failed", exc_info=True)
            return None


# Module-level singleton
agentic_rag_pipeline = AgenticRAGPipeline()
