"""Embedding generation and RAG retrieval for the agent memory system.

Provides:
    - EmbeddingService: thin wrapper around EmbeddingGateway (legacy API)
    - RAGPipeline: ingest → embed → store → retrieve → format context

The embedding service is called by the agent runtime before LLM calls
to enrich the conversation with relevant long-term memory context.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import structlog

from app.ai.embedding_gateway import embedding_gateway
from app.config import settings
from app.docprocessor.chunking import ChunkingStrategy, get_chunker

logger = structlog.stdlib.get_logger()

# Strip LLM role markers that could be used for prompt injection in RAG chunks.
_ROLE_MARKER_RE = re.compile(r"<\|?(system|assistant|user|im_start|im_end)\|?>")


class EmbeddingService:
    """Thin wrapper around EmbeddingGateway preserved for backward compatibility."""

    async def generate(self, text: str, *, model: str | None = None) -> list[float]:
        return await embedding_gateway.generate(text, model=model)

    async def generate_batch(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        return await embedding_gateway.generate_batch(texts, model=model)


class RAGPipeline:
    """Retrieval-Augmented Generation pipeline for agent memory.

    Orchestrates: query → embed → search memory → format context.
    """

    def __init__(self, embedding_service: EmbeddingService | None = None):
        self.embeddings = embedding_service or EmbeddingService()

    async def ingest_document(
        self,
        *,
        text: str,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        namespace: str = "rag",
        source: str = "",
        db: Any,
    ) -> int:
        """Chunk a document, generate embeddings, and store in long-term memory.

        Returns the number of chunks stored.
        """
        from app.agents.memory import AgentMemoryManager

        chunks = get_chunker(ChunkingStrategy.FIXED_SIZE).chunk(text)
        if not chunks:
            return 0

        chunk_texts = [chunk_text for chunk_text, _ in chunks]
        try:
            embeddings = await self.embeddings.generate_batch(chunk_texts)
        except Exception:
            logger.error("rag_embedding_generation_failed", exc_info=True)
            return 0

        memory = AgentMemoryManager(db)
        stored = 0
        model = settings.EMBEDDING_DEFAULT_MODEL

        for (chunk_text_str, meta), embedding in zip(chunks, embeddings, strict=False):
            key = f"doc:{meta.content_hash}:{meta.chunk_index}"
            await memory.set_long_term(
                instance_id=instance_id,
                tenant_id=tenant_id,
                key=key,
                value={
                    "text": chunk_text_str,
                    "chunk_index": meta.chunk_index,
                    "source": source,
                },
                namespace=namespace,
                embedding=embedding,
                embedding_model=model,
            )
            stored += 1

        await db.flush()
        logger.info(
            "rag_document_ingested",
            instance_id=str(instance_id),
            chunks=stored,
            source=source,
        )
        return stored

    async def retrieve(
        self,
        *,
        query: str,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        namespace: str = "rag",
        limit: int = 5,
        rerank: bool = False,
        db: Any,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant memory entries for a query.

        When rerank=True, over-fetches by 3x and applies re-ranking to
        improve precision before trimming to the requested limit.
        """
        from app.agents.memory import AgentMemoryManager

        try:
            query_embedding = await self.embeddings.generate(query)
        except Exception:
            logger.warning("rag_query_embedding_failed", exc_info=True)
            return []

        fetch_limit = limit * 3 if rerank else limit

        memory = AgentMemoryManager(db)
        results = await memory.search_by_embedding(
            instance_id=instance_id,
            tenant_id=tenant_id,
            query_embedding=query_embedding,
            namespace=namespace,
            limit=fetch_limit,
        )

        formatted = [
            {
                "text": r["value"].get("text", ""),
                "score": r["score"],
                "source": r["value"].get("source", ""),
                "key": r["key"],
            }
            for r in results
        ]

        if rerank and formatted:
            from app.agents.reranker import reranker as _reranker

            documents = [r["text"] for r in formatted]
            rerank_results = await _reranker.rerank(
                query=query,
                documents=documents,
                top_k=limit,
            )
            reranked = []
            for rr in rerank_results:
                if rr.index < len(formatted):
                    entry = formatted[rr.index].copy()
                    entry["score"] = rr.score
                    reranked.append(entry)
            return reranked

        return formatted[:limit]

    @staticmethod
    def _sanitize_rag_chunk(text: str) -> str:
        """Strip LLM role markers that could be used for prompt injection."""
        return _ROLE_MARKER_RE.sub("", text)[:4096]

    def format_context(self, results: list[dict[str, Any]]) -> str:
        """Format retrieved results as context for injection into system prompt."""
        if not results:
            return ""

        lines = ["## Relevant Context (from memory)"]
        for i, r in enumerate(results, 1):
            raw_source = r.get("source", "")
            if raw_source:
                sanitized_source = raw_source.replace("\n", " ").replace("\r", "")[:100]
                source = f" (source: {sanitized_source})"
            else:
                source = ""
            sanitized_text = self._sanitize_rag_chunk(r["text"])
            lines.append(f"{i}. {sanitized_text}{source}")

        return "\n".join(lines)


# Module-level singletons
embedding_service = EmbeddingService()
rag_pipeline = RAGPipeline(embedding_service)
