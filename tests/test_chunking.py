"""Tests for pluggable chunking strategies."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.docprocessor.chunking import (
    ChunkingStrategy,
    ChunkMetadata,
    FixedSizeChunker,
    MarkdownChunker,
    RecursiveChunker,
    SemanticChunker,
    get_chunker,
)


class TestFixedSizeChunker:
    def test_empty_text(self):
        chunker = FixedSizeChunker()
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []

    def test_short_text_single_chunk(self):
        chunker = FixedSizeChunker()
        result = chunker.chunk("Hello world", chunk_size=100)
        assert len(result) == 1
        assert result[0][0] == "Hello world"
        assert result[0][1].strategy == ChunkingStrategy.FIXED_SIZE
        assert result[0][1].chunk_index == 0

    def test_long_text_multiple_chunks(self):
        chunker = FixedSizeChunker()
        text = "word " * 500  # ~2500 chars
        result = chunker.chunk(text, chunk_size=200, chunk_overlap=50)
        assert len(result) > 1
        for i, (chunk_text, meta) in enumerate(result):
            assert meta.chunk_index == i
            assert meta.content_hash  # Non-empty hash

    def test_overlap_larger_than_size_is_capped(self):
        chunker = FixedSizeChunker()
        text = "a " * 100
        result = chunker.chunk(text, chunk_size=50, chunk_overlap=60)
        assert len(result) > 0  # Should not infinite loop

    def test_sentence_boundary_splitting(self):
        chunker = FixedSizeChunker()
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = chunker.chunk(text, chunk_size=40, chunk_overlap=10)
        # Should break at sentence boundaries
        assert len(result) >= 2


class TestRecursiveChunker:
    def test_empty_text(self):
        chunker = RecursiveChunker()
        assert chunker.chunk("") == []

    def test_short_text(self):
        chunker = RecursiveChunker()
        result = chunker.chunk("Hello", chunk_size=100)
        assert len(result) == 1

    def test_respects_paragraph_boundaries(self):
        chunker = RecursiveChunker()
        text = "Paragraph one content.\n\nParagraph two content.\n\nParagraph three content."
        result = chunker.chunk(text, chunk_size=40, chunk_overlap=0)
        assert len(result) >= 2
        for _, meta in result:
            assert meta.strategy == ChunkingStrategy.RECURSIVE

    def test_falls_to_finer_separators(self):
        chunker = RecursiveChunker()
        # Single paragraph that's too long
        text = "This is a long sentence. " * 20
        result = chunker.chunk(text, chunk_size=100, chunk_overlap=0)
        assert len(result) >= 2


class TestMarkdownChunker:
    def test_empty_text(self):
        chunker = MarkdownChunker()
        assert chunker.chunk("") == []

    def test_no_headings(self):
        chunker = MarkdownChunker()
        result = chunker.chunk("Just plain text without headings.")
        assert len(result) == 1
        assert result[0][1].strategy == ChunkingStrategy.MARKDOWN

    def test_splits_by_headings(self):
        chunker = MarkdownChunker()
        text = """# Title

Introduction paragraph.

## Section One

Content of section one.

## Section Two

Content of section two.
"""
        result = chunker.chunk(text, chunk_size=500)
        assert len(result) >= 2
        # Check heading hierarchy is tracked
        headings = [meta.section_title for _, meta in result if meta.section_title]
        assert any("Title" in h for h in headings) or any("Section" in h for h in headings)

    def test_preserves_code_blocks(self):
        chunker = MarkdownChunker()
        text = """# Code Example

```python
def hello():
    # This has a # character that should not be treated as heading
    print("hello")
```

## Next Section

More content.
"""
        result = chunker.chunk(text, chunk_size=500)
        # Code block should be intact in one chunk
        code_chunks = [t for t, _ in result if "def hello" in t]
        assert len(code_chunks) >= 1
        assert "print" in code_chunks[0]

    def test_heading_hierarchy(self):
        chunker = MarkdownChunker()
        text = """# Main

## Sub

Content.
"""
        result = chunker.chunk(text, chunk_size=500)
        # Find the chunk with "Sub" heading
        for _, meta in result:
            if meta.section_title and "Sub" in meta.section_title:
                assert len(meta.heading_hierarchy) >= 1
                break


class TestSemanticChunker:
    def test_sync_fallback_to_fixed(self):
        """Sync chunk() should fall back to FixedSizeChunker."""
        chunker = SemanticChunker()
        text = "First sentence. Second sentence. Third sentence."
        result = chunker.chunk(text, chunk_size=100)
        assert len(result) >= 1
        # Falls back to FIXED_SIZE strategy
        assert result[0][1].strategy == ChunkingStrategy.FIXED_SIZE

    def test_split_sentences(self):
        sentences = SemanticChunker._split_sentences(
            "Hello world. How are you? Fine thanks!"
        )
        assert len(sentences) == 3

    def test_cosine_similarity_identical(self):
        vec = [1.0, 0.0, 0.5]
        assert SemanticChunker._cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert SemanticChunker._cosine_similarity(a, b) == pytest.approx(0.0)


class TestGetChunker:
    def test_get_fixed_chunker(self):
        chunker = get_chunker(ChunkingStrategy.FIXED_SIZE)
        assert isinstance(chunker, FixedSizeChunker)

    def test_get_recursive_chunker(self):
        chunker = get_chunker(ChunkingStrategy.RECURSIVE)
        assert isinstance(chunker, RecursiveChunker)

    def test_get_markdown_chunker(self):
        chunker = get_chunker(ChunkingStrategy.MARKDOWN)
        assert isinstance(chunker, MarkdownChunker)

    def test_get_semantic_chunker(self):
        chunker = get_chunker(ChunkingStrategy.SEMANTIC)
        assert isinstance(chunker, SemanticChunker)

    def test_get_from_string(self):
        chunker = get_chunker("recursive")
        assert isinstance(chunker, RecursiveChunker)

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError):
            get_chunker("nonexistent")

    def test_default_from_settings(self):
        with patch("app.docprocessor.chunking.settings") as mock_settings:
            mock_settings.RAG_CHUNKING_STRATEGY = "markdown"
            mock_settings.RAG_CHUNK_SIZE = 1000
            mock_settings.RAG_CHUNK_OVERLAP = 200
            chunker = get_chunker(None)
            assert isinstance(chunker, MarkdownChunker)
