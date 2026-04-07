"""Index extracted content for RAG retrieval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.docprocessor.base import ExtractedTable, ExtractionResult

logger = structlog.stdlib.get_logger()


class ContentIndexer:
    """Index extracted content for RAG retrieval.

    Chunks extraction results and stores them as DataSourceChunk records
    with embeddings for vector search. Supports pluggable chunking strategies.
    """

    async def index_extraction(
        self,
        extraction: ExtractionResult,
        data_source_id: UUID,
        tenant_id: UUID,
        db: AsyncSession,
        *,
        chunking_strategy: str | None = None,
    ) -> int:
        """Chunk and embed extracted content. Returns chunk count.

        Args:
            extraction: The extraction result to index.
            data_source_id: ID of the DataSource record.
            tenant_id: Tenant owning the data.
            db: Async database session.
            chunking_strategy: Override chunking strategy (default from config).

        Returns:
            Number of chunks stored.
        """
        from app.agents.embeddings import EmbeddingService
        from app.db.models.datasource import DataSourceChunk
        from app.docprocessor.chunking import get_chunker

        # Verify tenant ownership (defense-in-depth against mismatched IDs)
        if hasattr(db, "get"):
            from app.db.models.datasource import DataSource

            ds = await db.get(DataSource, data_source_id)
            if ds and str(ds.tenant_id) != str(tenant_id):
                raise ValueError(
                    f"Tenant mismatch: datasource {data_source_id} belongs to "
                    f"{ds.tenant_id}, not {tenant_id}"
                )

        # Build chunks using pluggable strategy
        chunker = get_chunker(chunking_strategy)
        text_chunk_tuples = chunker.chunk(extraction.raw_text) if extraction.raw_text else []
        text_chunks = [text for text, _ in text_chunk_tuples]
        text_metadata = [meta for _, meta in text_chunk_tuples]

        table_chunks = self._chunk_tables(extraction.tables)
        all_chunks = text_chunks + table_chunks

        if not all_chunks:
            logger.info("no_chunks_to_index", data_source_id=str(data_source_id))
            return 0

        # Generate embeddings
        embedding_service = EmbeddingService()
        try:
            embeddings = await embedding_service.generate_batch(all_chunks)
        except Exception:
            logger.error(
                "embedding_generation_failed",
                data_source_id=str(data_source_id),
                exc_info=True,
            )
            # Store chunks without embeddings rather than failing entirely
            embeddings = [None] * len(all_chunks)

        # Convert embeddings to pgvector format string for native vector column
        def _to_vector_str(emb: list[float] | None) -> str | None:
            if emb is None:
                return None
            from app.ai.embedding_gateway import embedding_to_vector_str

            try:
                return embedding_to_vector_str(emb)
            except ValueError:
                logger.warning("invalid_embedding_values", exc_info=True)
                return None

        # Ensure embeddings list matches chunks (pad with None if partial failure)
        if len(embeddings) < len(all_chunks):
            logger.warning(
                "partial_embedding_generation",
                data_source_id=str(data_source_id),
                expected=len(all_chunks),
                got=len(embeddings),
            )
            embeddings.extend([None] * (len(all_chunks) - len(embeddings)))

        stored = 0
        now = datetime.now(UTC)
        for idx, (chunk_text, embedding) in enumerate(zip(all_chunks, embeddings, strict=True)):
            # Determine section title for the chunk
            section_title = None
            if idx < len(text_chunks):
                # Use metadata from chunker if available
                if idx < len(text_metadata) and text_metadata[idx].section_title:
                    section_title = text_metadata[idx].section_title
                else:
                    for section in extraction.sections:
                        if chunk_text[:100] in section.content:
                            section_title = section.title
                            break
            else:
                section_title = "Table Data"

            embedding_model = settings.EMBEDDING_DEFAULT_MODEL if embedding else None

            vec_str = _to_vector_str(embedding)
            chunk = DataSourceChunk(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                data_source_id=data_source_id,
                chunk_index=idx,
                content=chunk_text,
                # Write to JSONB (backward compat), full-precision vector, and halfvec
                embedding=embedding,
                embedding_vec=vec_str,
                embedding_halfvec=vec_str,  # PostgreSQL casts vector→halfvec automatically
                embedding_model=embedding_model,
                section_title=section_title,
                table_index=idx - len(text_chunks) if idx >= len(text_chunks) else None,
                content_type=extraction.source_type,
                indexed_at=now,
            )
            db.add(chunk)
            stored += 1

        await db.flush()
        logger.info(
            "content_indexed",
            data_source_id=str(data_source_id),
            chunks=stored,
            text_chunks=len(text_chunks),
            table_chunks=len(table_chunks),
            strategy=chunking_strategy or settings.RAG_CHUNKING_STRATEGY,
        )
        return stored

    def _chunk_tables(self, tables: list[ExtractedTable]) -> list[str]:
        """Convert tables to text chunks serialized as markdown tables.

        Each table becomes one or more chunks depending on size.
        """
        chunks: list[str] = []
        for table in tables:
            md = self._table_to_markdown(table)
            if not md.strip():
                continue
            # If the markdown table is small enough, keep as one chunk
            if len(md) <= 1200:
                chunks.append(md)
            else:
                # Split large tables into row groups
                header_line = "| " + " | ".join(table.headers) + " |"
                sep_line = "| " + " | ".join("---" for _ in table.headers) + " |"
                header_block = f"{header_line}\n{sep_line}"

                current_lines = [header_block]
                current_len = len(header_block)

                for row in table.rows:
                    row_line = "| " + " | ".join(row) + " |"
                    if current_len + len(row_line) + 1 > 1000 and len(current_lines) > 1:
                        chunks.append("\n".join(current_lines))
                        current_lines = [header_block]
                        current_len = len(header_block)
                    current_lines.append(row_line)
                    current_len += len(row_line) + 1

                if len(current_lines) > 1:
                    chunks.append("\n".join(current_lines))

        return chunks

    @staticmethod
    def _table_to_markdown(table: ExtractedTable) -> str:
        """Convert an ExtractedTable to a markdown table string."""
        if not table.headers:
            return ""

        lines = [
            "| " + " | ".join(table.headers) + " |",
            "| " + " | ".join("---" for _ in table.headers) + " |",
        ]
        for row in table.rows:
            # Pad or truncate row to match header length
            padded = row + [""] * (len(table.headers) - len(row)) if len(row) < len(table.headers) else row[:len(table.headers)]
            lines.append("| " + " | ".join(padded) + " |")
        return "\n".join(lines)
