"""Graph RAG: knowledge graph construction and graph-enhanced retrieval.

Extracts entities and relationships from document chunks using LLM,
stores them in PostgreSQL, and augments vector search results with
graph-connected chunks for relationship-aware retrieval.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.search import SearchResult, SearchSource, SearchType
from app.config import settings

logger = structlog.stdlib.get_logger()


class GraphRAGEngine:
    """Graph-enhanced retrieval using extracted knowledge graphs."""

    async def augment_results(
        self,
        results: list[SearchResult],
        tenant_id: uuid.UUID,
        db: AsyncSession,
        *,
        max_graph_results: int = 5,
    ) -> list[SearchResult]:
        """Augment vector search results with graph-connected chunks.

        For each result, finds entities mentioned in the chunk, traverses
        relationships, and retrieves chunks that mention connected entities.
        """
        if not settings.RAG_GRAPH_ENABLED or not results:
            return results

        # Collect entity IDs from result chunks
        chunk_ids = [r.id for r in results if r.source == SearchSource.CHUNKS]
        if not chunk_ids:
            return results

        try:
            # Find entities connected to the result chunks via relationships
            sql = """
                WITH result_entities AS (
                    SELECT DISTINCT re.id AS entity_id
                    FROM rag_relationships rr
                    JOIN rag_entities re ON re.id = rr.source_entity_id OR re.id = rr.target_entity_id
                    WHERE rr.tenant_id = :tenant_id
                      AND rr.chunk_id = ANY(:chunk_ids)
                ),
                connected_entities AS (
                    SELECT DISTINCT
                        CASE WHEN rr.source_entity_id IN (SELECT entity_id FROM result_entities)
                             THEN rr.target_entity_id
                             ELSE rr.source_entity_id
                        END AS entity_id,
                        rr.weight,
                        rr.chunk_id
                    FROM rag_relationships rr
                    WHERE rr.tenant_id = :tenant_id
                      AND (rr.source_entity_id IN (SELECT entity_id FROM result_entities)
                           OR rr.target_entity_id IN (SELECT entity_id FROM result_entities))
                      AND rr.chunk_id IS NOT NULL
                      AND rr.chunk_id != ALL(:chunk_ids)
                    ORDER BY rr.weight DESC
                    LIMIT :max_results
                )
                SELECT dsc.id::text, dsc.content, dsc.data_source_id::text,
                       dsc.section_title, dsc.content_type,
                       ce.weight AS graph_weight
                FROM connected_entities ce
                JOIN data_source_chunks dsc ON dsc.id = ce.chunk_id
                WHERE dsc.tenant_id = :tenant_id
            """

            result = await db.execute(text(sql), {
                "tenant_id": str(tenant_id),
                "chunk_ids": chunk_ids,
                "max_results": max_graph_results,
            })
            rows = result.mappings().all()

            # Add graph results with reduced score (graph connections are secondary)
            existing_ids = {r.id for r in results}
            min_score = min(r.score for r in results) if results else 0.0

            for row in rows:
                if str(row["id"]) not in existing_ids:
                    results.append(SearchResult(
                        id=str(row["id"]),
                        content=row["content"] or "",
                        score=min_score * 0.8 * float(row["graph_weight"]),
                        source=SearchSource.CHUNKS,
                        source_id=str(row["data_source_id"]) if row["data_source_id"] else "",
                        metadata={
                            "section_title": row["section_title"],
                            "content_type": row["content_type"],
                            "source": "graph_rag",
                        },
                        search_type=SearchType.HYBRID,
                    ))

            if rows:
                logger.info(
                    "graph_rag_augmented",
                    original_results=len(chunk_ids),
                    graph_results=len(rows),
                )

        except Exception:
            logger.warning("graph_rag_augmentation_failed", exc_info=True)

        return results


# Module-level singleton
graph_rag_engine = GraphRAGEngine()
