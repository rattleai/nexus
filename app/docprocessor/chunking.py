"""Pluggable chunking strategies for document processing and RAG.

Provides four strategies:
  - FixedSizeChunker: fixed-size with overlap (backward-compatible default)
  - RecursiveChunker: recursive character splitting by separator hierarchy
  - MarkdownChunker: heading-aware splitting that preserves structure
  - SemanticChunker: groups sentences by embedding similarity

All chunkers produce (text, ChunkMetadata) tuples for uniform downstream
handling by ContentIndexer and RAGPipeline.
"""

from __future__ import annotations

import enum
import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.config import settings


class ChunkingStrategy(enum.StrEnum):
    FIXED_SIZE = "fixed_size"
    RECURSIVE = "recursive"
    MARKDOWN = "markdown"
    SEMANTIC = "semantic"


@dataclass
class ChunkMetadata:
    """Metadata attached to each chunk."""

    chunk_index: int
    content_hash: str
    strategy: ChunkingStrategy
    section_title: str | None = None
    heading_hierarchy: list[str] = field(default_factory=list)


# Maximum chunks per document (safety cap)
_MAX_CHUNKS = 500


class Chunker(ABC):
    """Base class for chunking strategies."""

    @abstractmethod
    def chunk(
        self,
        text: str,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        **kwargs: Any,
    ) -> list[tuple[str, ChunkMetadata]]:
        """Split text into chunks with metadata.

        Returns list of (chunk_text, metadata) tuples.
        """
        ...


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class FixedSizeChunker(Chunker):
    """Fixed-size chunking with overlap, breaking at sentence boundaries.

    This is the original chunking strategy extracted from embeddings.py and
    indexer.py for backward compatibility.
    """

    def chunk(
        self,
        text: str,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        **kwargs: Any,
    ) -> list[tuple[str, ChunkMetadata]]:
        chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
        chunk_overlap = chunk_overlap or settings.RAG_CHUNK_OVERLAP

        if not text or not text.strip():
            return []

        if chunk_overlap >= chunk_size:
            chunk_overlap = chunk_size // 2

        results: list[tuple[str, ChunkMetadata]] = []
        start = 0
        idx = 0

        while start < len(text) and idx < _MAX_CHUNKS:
            end = start + chunk_size

            if end < len(text):
                for sep in ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]:
                    boundary = text.rfind(sep, start + chunk_size // 2, end)
                    if boundary > start:
                        end = boundary + len(sep)
                        break

            chunk_text = text[start:end].strip()
            if chunk_text:
                results.append((
                    chunk_text,
                    ChunkMetadata(
                        chunk_index=idx,
                        content_hash=_content_hash(chunk_text),
                        strategy=ChunkingStrategy.FIXED_SIZE,
                    ),
                ))
                idx += 1

            start = end - chunk_overlap
            if start <= 0 and idx > 0:
                break

        return results


class RecursiveChunker(Chunker):
    """Recursive character splitting by separator hierarchy.

    Tries the most meaningful separators first (paragraphs, then lines,
    then sentences, then words). Falls to the next separator level when
    chunks exceed the target size.
    """

    _SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " "]

    def chunk(
        self,
        text: str,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        **kwargs: Any,
    ) -> list[tuple[str, ChunkMetadata]]:
        chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
        chunk_overlap = chunk_overlap or settings.RAG_CHUNK_OVERLAP

        if not text or not text.strip():
            return []

        raw_chunks = self._split_recursive(text, self._SEPARATORS, chunk_size)
        # Merge small chunks and apply overlap
        merged = self._merge_with_overlap(raw_chunks, chunk_size, chunk_overlap)

        results: list[tuple[str, ChunkMetadata]] = []
        for idx, chunk_text in enumerate(merged[:_MAX_CHUNKS]):
            if chunk_text.strip():
                results.append((
                    chunk_text.strip(),
                    ChunkMetadata(
                        chunk_index=idx,
                        content_hash=_content_hash(chunk_text.strip()),
                        strategy=ChunkingStrategy.RECURSIVE,
                    ),
                ))
        return results

    def _split_recursive(
        self, text: str, separators: list[str], chunk_size: int,
    ) -> list[str]:
        """Recursively split text using separator hierarchy."""
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        if not separators:
            # No more separators — hard split
            return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

        sep = separators[0]
        remaining_seps = separators[1:]
        parts = text.split(sep)

        chunks: list[str] = []
        current = ""

        for part in parts:
            candidate = current + sep + part if current else part
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                if len(part) > chunk_size:
                    chunks.extend(self._split_recursive(part, remaining_seps, chunk_size))
                    current = ""
                else:
                    current = part

        if current.strip():
            chunks.append(current)
        return chunks

    def _merge_with_overlap(
        self, chunks: list[str], chunk_size: int, overlap: int,
    ) -> list[str]:
        """Add overlap between consecutive chunks."""
        if not chunks or overlap <= 0:
            return chunks

        result = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            overlap_text = prev[-overlap:] if len(prev) > overlap else prev
            merged = overlap_text + chunks[i]
            if len(merged) <= chunk_size * 1.2:
                result.append(merged)
            else:
                result.append(chunks[i])
        return result


class MarkdownChunker(Chunker):
    """Heading-aware chunking that preserves markdown structure.

    Splits at heading boundaries (#, ##, ###), preserves heading hierarchy
    in metadata, and keeps code blocks and tables intact.
    """

    _HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    _CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```", re.MULTILINE)

    def chunk(
        self,
        text: str,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        **kwargs: Any,
    ) -> list[tuple[str, ChunkMetadata]]:
        chunk_size = chunk_size or settings.RAG_CHUNK_SIZE

        if not text or not text.strip():
            return []

        # Find all headings and their positions
        sections = self._split_by_headings(text)
        results: list[tuple[str, ChunkMetadata]] = []
        idx = 0
        heading_stack: list[str] = []

        for heading, content, level in sections:
            if heading:
                # Update heading stack
                while heading_stack and len(heading_stack) >= level:
                    heading_stack.pop()
                heading_stack.append(heading)

            full_text = f"{heading}\n\n{content}".strip() if heading else content.strip()
            if not full_text:
                continue

            if len(full_text) <= chunk_size:
                results.append((
                    full_text,
                    ChunkMetadata(
                        chunk_index=idx,
                        content_hash=_content_hash(full_text),
                        strategy=ChunkingStrategy.MARKDOWN,
                        section_title=heading or None,
                        heading_hierarchy=list(heading_stack),
                    ),
                ))
                idx += 1
            else:
                # Sub-chunk large sections with FixedSizeChunker
                sub_chunker = FixedSizeChunker()
                sub_chunks = sub_chunker.chunk(full_text, chunk_size=chunk_size)
                for sub_text, _ in sub_chunks:
                    if idx >= _MAX_CHUNKS:
                        break
                    results.append((
                        sub_text,
                        ChunkMetadata(
                            chunk_index=idx,
                            content_hash=_content_hash(sub_text),
                            strategy=ChunkingStrategy.MARKDOWN,
                            section_title=heading or None,
                            heading_hierarchy=list(heading_stack),
                        ),
                    ))
                    idx += 1

            if idx >= _MAX_CHUNKS:
                break

        return results

    def _split_by_headings(self, text: str) -> list[tuple[str, str, int]]:
        """Split text into (heading, content, level) tuples."""
        # Protect code blocks from heading splitting.
        # Uses UUID-based markers to avoid collision with actual text content.
        import uuid as _uuid

        protected: dict[str, str] = {}

        def protect_code(match: re.Match) -> str:
            key = f"\x00CODEBLOCK_{_uuid.uuid4().hex}\x00"
            protected[key] = match.group(0)
            return key

        safe_text = self._CODE_BLOCK_PATTERN.sub(protect_code, text)

        headings = list(self._HEADING_PATTERN.finditer(safe_text))
        if not headings:
            restored = text
            return [("", restored, 0)]

        sections: list[tuple[str, str, int]] = []

        # Content before first heading
        if headings[0].start() > 0:
            pre_content = safe_text[:headings[0].start()]
            for key, val in protected.items():
                pre_content = pre_content.replace(key, val)
            if pre_content.strip():
                sections.append(("", pre_content.strip(), 0))

        for i, match in enumerate(headings):
            level = len(match.group(1))
            heading = match.group(0)
            start = match.end()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(safe_text)
            content = safe_text[start:end]
            # Restore code blocks
            for key, val in protected.items():
                heading = heading.replace(key, val)
                content = content.replace(key, val)
            sections.append((heading, content.strip(), level))

        return sections


class SemanticChunker(Chunker):
    """Groups sentences by embedding similarity.

    Splits text at sentence boundaries, computes embeddings for each
    sentence, then merges consecutive sentences where cosine similarity
    exceeds a threshold. Splits when similarity drops below the threshold.

    Requires an embedding gateway for computing sentence embeddings.
    Falls back to FixedSizeChunker if embeddings are unavailable.
    """

    def chunk(
        self,
        text: str,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        **kwargs: Any,
    ) -> list[tuple[str, ChunkMetadata]]:
        # SemanticChunker requires async for embeddings. This sync method
        # is a fallback that delegates to FixedSizeChunker.
        # Use chunk_async() for the full semantic pipeline.
        return FixedSizeChunker().chunk(
            text, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        )

    async def chunk_async(
        self,
        text: str,
        *,
        chunk_size: int | None = None,
        threshold: float | None = None,
        **kwargs: Any,
    ) -> list[tuple[str, ChunkMetadata]]:
        """Async semantic chunking using embeddings."""
        chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
        threshold = threshold or settings.RAG_SEMANTIC_SIMILARITY_THRESHOLD

        if not text or not text.strip():
            return []

        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            return FixedSizeChunker().chunk(text, chunk_size=chunk_size)

        try:
            from app.ai.embedding_gateway import embedding_gateway

            embeddings = await embedding_gateway.generate_batch(sentences)
        except Exception:
            return FixedSizeChunker().chunk(text, chunk_size=chunk_size)

        # Group sentences by similarity
        groups: list[list[str]] = [[sentences[0]]]
        for i in range(1, len(sentences)):
            sim = self._cosine_similarity(embeddings[i - 1], embeddings[i])
            current_group_text = " ".join(groups[-1])
            candidate = current_group_text + " " + sentences[i]
            if sim >= threshold and len(candidate) <= chunk_size:
                groups[-1].append(sentences[i])
            else:
                groups.append([sentences[i]])

        results: list[tuple[str, ChunkMetadata]] = []
        for idx, group in enumerate(groups[:_MAX_CHUNKS]):
            chunk_text = " ".join(group).strip()
            if chunk_text:
                results.append((
                    chunk_text,
                    ChunkMetadata(
                        chunk_index=idx,
                        content_hash=_content_hash(chunk_text),
                        strategy=ChunkingStrategy.SEMANTIC,
                    ),
                ))
        return results

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


def get_chunker(strategy: ChunkingStrategy | str | None = None) -> Chunker:
    """Factory function to get a chunker by strategy name."""
    if strategy is None:
        strategy = settings.RAG_CHUNKING_STRATEGY

    if isinstance(strategy, str):
        strategy = ChunkingStrategy(strategy)

    chunker_map: dict[ChunkingStrategy, type[Chunker]] = {
        ChunkingStrategy.FIXED_SIZE: FixedSizeChunker,
        ChunkingStrategy.RECURSIVE: RecursiveChunker,
        ChunkingStrategy.MARKDOWN: MarkdownChunker,
        ChunkingStrategy.SEMANTIC: SemanticChunker,
    }

    cls = chunker_map.get(strategy)
    if not cls:
        raise ValueError(f"Unknown chunking strategy: {strategy}")
    return cls()
