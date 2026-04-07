"""Embedding generation and RAG retrieval for the agent memory system.

Provides:
    - Embedding generation via OpenAI, Anthropic, or local models
    - Document chunking for long-form content
    - RAG retrieval: query embeddings → memory search → context injection

The embedding service is called by the agent runtime before LLM calls
to enrich the conversation with relevant long-term memory context.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()

# Default chunk size and overlap for document splitting
_DEFAULT_CHUNK_SIZE = 1000
_DEFAULT_CHUNK_OVERLAP = 200
_MAX_CHUNKS_PER_DOCUMENT = 500


class EmbeddingService:
    """Generates vector embeddings for text using the multi-provider gateway.

    Delegates to EmbeddingGateway for provider-agnostic embedding generation
    with caching, circuit breaker, and multi-provider support.
    """

    def __init__(self):
        self._model = settings.EMBEDDING_DEFAULT_MODEL
        self._dimensions = settings.AGENT_MEMORY_VECTOR_DIMENSIONS

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
    ) -> list[float]:
        """Generate an embedding vector for the given text."""
        from app.ai.embedding_gateway import embedding_gateway

        return await embedding_gateway.generate(text, model=model or self._model)

    async def generate_batch(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        from app.ai.embedding_gateway import embedding_gateway

        return await embedding_gateway.generate_batch(texts, model=model or self._model)


def chunk_text(
    text: str,
    *,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """Split text into overlapping chunks for embedding.

    Returns list of {"text": str, "chunk_index": int, "content_hash": str}.
    """
    if not text or not text.strip():
        return []

    # Guard against infinite loop when overlap >= size
    if chunk_overlap >= chunk_size:
        chunk_overlap = chunk_size // 2

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text) and chunk_index < _MAX_CHUNKS_PER_DOCUMENT:
        end = start + chunk_size

        # Try to break at a sentence boundary
        if end < len(text):
            for sep in ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]:
                boundary = text.rfind(sep, start + chunk_size // 2, end)
                if boundary > start:
                    end = boundary + len(sep)
                    break

        chunk_text_str = text[start:end].strip()
        if chunk_text_str:
            chunks.append({
                "text": chunk_text_str,
                "chunk_index": chunk_index,
                "content_hash": hashlib.sha256(chunk_text_str.encode()).hexdigest()[:16],
            })
            chunk_index += 1

        start = end - chunk_overlap
        if start <= 0 and chunk_index > 0:
            break  # Prevent infinite loop on tiny text

    return chunks


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

        chunks = chunk_text(text)
        if not chunks:
            return 0

        # Generate embeddings in batch
        chunk_texts = [c["text"] for c in chunks]
        try:
            embeddings = await self.embeddings.generate_batch(chunk_texts)
        except Exception:
            logger.error("rag_embedding_generation_failed", exc_info=True)
            return 0

        memory = AgentMemoryManager(db)
        stored = 0

        for chunk, embedding in zip(chunks, embeddings, strict=False):
            key = f"doc:{chunk['content_hash']}:{chunk['chunk_index']}"
            await memory.set_long_term(
                instance_id=instance_id,
                tenant_id=tenant_id,
                key=key,
                value={
                    "text": chunk["text"],
                    "chunk_index": chunk["chunk_index"],
                    "source": source,
                },
                namespace=namespace,
                embedding=embedding,
                embedding_model=self.embeddings._model,
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

        Returns ranked list of {"text": str, "score": float, "source": str}.

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

        # Apply re-ranking if requested and results exist
        if rerank and formatted:
            from app.agents.reranker import reranker as _reranker

            documents = [r["text"] for r in formatted]
            rerank_results = await _reranker.rerank(
                query=query, documents=documents, top_k=limit,
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
        """Strip characters that could be used for prompt injection in RAG chunks."""
        # Remove system/assistant role markers that could confuse the LLM
        import re
        sanitized = re.sub(r'<\|?(system|assistant|user|im_start|im_end)\|?>', '', text)
        # Limit chunk size
        return sanitized[:4096]

    def format_context(self, results: list[dict[str, Any]]) -> str:
        """Format retrieved results as context for injection into system prompt."""
        if not results:
            return ""

        lines = ["## Relevant Context (from memory)"]
        for i, r in enumerate(results, 1):
            # Sanitize source to prevent prompt injection via RAG context
            raw_source = r.get("source", "")
            if raw_source:
                # Strip control characters and limit length
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
