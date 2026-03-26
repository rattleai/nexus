"""Index extracted content for RAG retrieval."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.docprocessor.base import ExtractedTable, ExtractionResult

logger = structlog.stdlib.get_logger()


class ContentIndexer:
    """Index extracted content for RAG retrieval.

    Chunks extraction results and stores them as DataSourceChunk records
    with embeddings for vector search.
    """

    async def index_extraction(
        self,
        extraction: ExtractionResult,
        data_source_id: UUID,
        tenant_id: UUID,
        db: AsyncSession,
    ) -> int:
        """Chunk and embed extracted content. Returns chunk count.

        Args:
            extraction: The extraction result to index.
            data_source_id: ID of the DataSource record.
            tenant_id: Tenant owning the data.
            db: Async database session.

        Returns:
            Number of chunks stored.
        """
        from app.agents.embeddings import EmbeddingService
        from app.db.models.datasource import DataSourceChunk

        # Verify tenant ownership (defense-in-depth against mismatched IDs)
        if hasattr(db, "get"):
            from app.db.models.datasource import DataSource

            ds = await db.get(DataSource, data_source_id)
            if ds and str(ds.tenant_id) != str(tenant_id):
                raise ValueError(
                    f"Tenant mismatch: datasource {data_source_id} belongs to "
                    f"{ds.tenant_id}, not {tenant_id}"
                )

        # Build chunks from text and tables
        text_chunks = self._chunk_text(extraction.raw_text)
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

        stored = 0
        for idx, (chunk_text, embedding) in enumerate(zip(all_chunks, embeddings, strict=False)):
            # Determine section title for the chunk
            section_title = None
            if idx < len(text_chunks):
                # Try to find the section this text chunk belongs to
                for section in extraction.sections:
                    if chunk_text[:100] in section.content:
                        section_title = section.title
                        break
            else:
                section_title = "Table Data"

            chunk = DataSourceChunk(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                data_source_id=data_source_id,
                chunk_index=idx,
                content=chunk_text,
                embedding=embedding,
                embedding_model="text-embedding-3-small" if embedding else None,
                section_title=section_title,
                table_index=idx - len(text_chunks) if idx >= len(text_chunks) else None,
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
        )
        return stored

    def _chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
        """Split text into overlapping chunks.

        Uses sentence-boundary-aware splitting to avoid breaking mid-sentence.
        """
        if not text or not text.strip():
            return []

        # Guard against infinite loop
        if overlap >= chunk_size:
            overlap = chunk_size // 2

        chunks: list[str] = []
        start = 0
        max_chunks = 500  # Safety cap

        while start < len(text) and len(chunks) < max_chunks:
            end = start + chunk_size

            # Try to break at a natural boundary
            if end < len(text):
                for sep in ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]:
                    boundary = text.rfind(sep, start + chunk_size // 2, end)
                    if boundary > start:
                        end = boundary + len(sep)
                        break

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - overlap
            if start <= 0 and len(chunks) > 0:
                break

        return chunks

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
