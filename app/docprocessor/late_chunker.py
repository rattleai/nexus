"""Late chunking: Jina-style embed-then-split for cross-chunk context.

Traditional chunking embeds each chunk independently, losing cross-chunk
context. Late chunking embeds the full document through a long-context
model, then splits the embedding sequence at chunk boundaries. This
preserves the full document context in every chunk's embedding.

Constraint: requires a long-context embedding model that returns
per-token embeddings (LOCAL or Jina providers). Falls back to
FixedSizeChunker with standard embedding if per-token embeddings
are not available.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.config import settings
from app.docprocessor.chunking import (
    ChunkMetadata,
    ChunkingStrategy,
    Chunker,
    FixedSizeChunker,
)

logger = structlog.stdlib.get_logger()


class LateChunker(Chunker):
    """Late chunking: split text using standard chunking, but flag for late embedding.

    The actual late embedding (embed full doc, then pool per chunk) happens
    in the indexer when the embedding provider supports per-token embeddings.
    This chunker produces the same chunk boundaries as FixedSizeChunker but
    marks them with the LATE strategy for downstream handling.
    """

    def chunk(
        self,
        text: str,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        **kwargs: Any,
    ) -> list[tuple[str, ChunkMetadata]]:
        """Split text into chunks marked for late embedding."""
        if not settings.RAG_LATE_CHUNKING_ENABLED:
            logger.warning(
                "late_chunking_disabled",
                detail="RAG_LATE_CHUNKING_ENABLED is False, falling back to fixed_size",
            )
            return FixedSizeChunker().chunk(
                text, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
            )

        # Use fixed-size chunking for boundaries, but mark with LATE strategy
        base_chunks = FixedSizeChunker().chunk(
            text, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        )

        # Re-tag metadata with LATE strategy
        return [
            (chunk_text, ChunkMetadata(
                chunk_index=meta.chunk_index,
                content_hash=meta.content_hash,
                strategy=ChunkingStrategy.LATE,
                section_title=meta.section_title,
                heading_hierarchy=meta.heading_hierarchy,
            ))
            for chunk_text, meta in base_chunks
        ]
