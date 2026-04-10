"""Query decomposition: split complex queries into simpler sub-queries.

When a user asks a multi-part question like "What is the pricing for X
and how does it compare to Y?", this module splits it into independent
sub-queries, executes each, and merges results with deduplication.

Uses a cheap LLM call for decomposition, falls back to the original
query if decomposition fails.
"""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


class QueryDecomposer:
    """Decompose complex queries into simpler sub-queries."""

    async def decompose(self, query: str) -> list[str]:
        """Split a complex query into independent sub-queries.

        Returns the original query as a single-item list if decomposition
        is not needed or fails.
        """
        if not settings.RAG_QUERY_DECOMPOSITION_ENABLED:
            return [query]

        try:
            from app.ai.gateway import ai_gateway

            response = await ai_gateway.complete(
                model=settings.RAG_CONTEXTUAL_MODEL,  # Cheap model (Haiku)
                messages=[{
                    "role": "user",
                    "content": (
                        "Split this query into independent sub-questions. "
                        "Return each sub-question on a separate line. "
                        "If the query is already simple, return it unchanged.\n\n"
                        f"Query: {query}"
                    ),
                }],
                max_tokens=200,
                temperature=0.0,
            )

            content = ""
            if response and hasattr(response, "content"):
                content = response.content
            elif isinstance(response, dict):
                content = response.get("content", "")

            sub_queries = [
                line.strip().lstrip("0123456789.-) ")
                for line in content.strip().split("\n")
                if line.strip() and len(line.strip()) > 5
            ]

            if not sub_queries:
                return [query]

            logger.info(
                "query_decomposed",
                original=query[:100],
                sub_queries=len(sub_queries),
            )
            return sub_queries[:5]  # Cap at 5 sub-queries

        except Exception:
            logger.warning("query_decomposition_failed", exc_info=True)
            return [query]


# Module-level singleton
query_decomposer = QueryDecomposer()
