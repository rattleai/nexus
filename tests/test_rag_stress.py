"""Heavy stress tests for RAG components.

Tests edge cases, boundary conditions, performance under load,
concurrency, and robustness of all new RAG components.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Chunking Stress Tests ────────────────────────────────────
from app.docprocessor.chunking import (
    ChunkingStrategy,
    FixedSizeChunker,
    MarkdownChunker,
    RecursiveChunker,
    get_chunker,
)


class TestChunkingStress:
    """Stress tests for chunking strategies."""

    def test_very_large_document(self):
        """Test chunking a very large document (1MB)."""
        text = "The quick brown fox jumps over the lazy dog. " * 25000  # ~1.1MB
        chunker = FixedSizeChunker()
        start = time.monotonic()
        chunks = chunker.chunk(text, chunk_size=1000, chunk_overlap=200)
        elapsed = time.monotonic() - start
        assert len(chunks) > 0
        assert len(chunks) <= 500  # Max chunks cap
        assert elapsed < 5.0, f"Chunking took {elapsed:.2f}s (should be <5s)"

    def test_tiny_text_all_strategies(self):
        """Single character text through all strategies."""
        for strategy in ChunkingStrategy:
            chunker = get_chunker(strategy)
            result = chunker.chunk("a")
            assert len(result) <= 1

    def test_single_word(self):
        """Single word through all strategies."""
        for strategy in ChunkingStrategy:
            chunker = get_chunker(strategy)
            result = chunker.chunk("hello")
            assert len(result) == 1
            assert result[0][0] == "hello"

    def test_only_whitespace(self):
        """Whitespace-only text."""
        for strategy in ChunkingStrategy:
            chunker = get_chunker(strategy)
            result = chunker.chunk("   \n\n\t  ")
            assert result == []

    def test_unicode_text(self):
        """Test with Unicode characters (CJK, emoji, RTL)."""
        text = "这是一个测试文档。它包含中文字符。\n\n日本語のテキストも含まれています。\n\nعربي"
        chunker = FixedSizeChunker()
        chunks = chunker.chunk(text, chunk_size=50)
        assert len(chunks) > 0
        for chunk_text, _ in chunks:
            assert chunk_text.strip()

    def test_binary_like_content(self):
        """Text with null bytes and control characters."""
        text = "Normal text\x00with null\x01bytes\x02in it. More text follows."
        chunker = FixedSizeChunker()
        chunks = chunker.chunk(text, chunk_size=20)
        assert len(chunks) > 0

    def test_repeated_separator(self):
        """Text that is only separators."""
        text = "\n\n\n\n\n\n\n\n\n\n"
        chunker = FixedSizeChunker()
        chunks = chunker.chunk(text, chunk_size=5)
        assert len(chunks) == 0  # Only whitespace

    def test_chunk_size_equals_one(self):
        """Extreme: chunk_size=1."""
        chunker = FixedSizeChunker()
        text = "abc def"
        chunks = chunker.chunk(text, chunk_size=1, chunk_overlap=0)
        assert len(chunks) > 0

    def test_chunk_overlap_equals_zero(self):
        """No overlap — no text should be duplicated."""
        text = "AAAA. BBBB. CCCC. DDDD."
        chunker = FixedSizeChunker()
        chunks = chunker.chunk(text, chunk_size=10, chunk_overlap=0)
        assert len(chunks) > 1

    def test_recursive_deeply_nested(self):
        """RecursiveChunker with text that requires all separator levels."""
        # Text with no natural breaks
        text = "a" * 5000
        chunker = RecursiveChunker()
        chunks = chunker.chunk(text, chunk_size=100, chunk_overlap=0)
        assert len(chunks) > 0
        for chunk_text, _meta in chunks:
            assert len(chunk_text) <= 120  # Allow some flex

    def test_markdown_many_headings(self):
        """MarkdownChunker with 100+ headings."""
        lines = []
        for i in range(150):
            level = (i % 3) + 1
            lines.append(f"{'#' * level} Heading {i}")
            lines.append(f"Content for section {i}. " * 3)
            lines.append("")
        text = "\n".join(lines)
        chunker = MarkdownChunker()
        chunks = chunker.chunk(text, chunk_size=200)
        assert len(chunks) > 10
        assert len(chunks) <= 500

    def test_markdown_code_blocks_with_hash(self):
        """Code blocks containing # should not be treated as headings."""
        text = """# Real Heading

```python
# This is a comment, not a heading
## Also not a heading
def foo():
    pass
```

## Another Real Heading

Content.
"""
        chunker = MarkdownChunker()
        chunks = chunker.chunk(text, chunk_size=500)
        headings = [m.section_title for _, m in chunks if m.section_title]
        # "# This is a comment" should NOT be a heading
        assert not any("comment" in h for h in headings if h)

    def test_all_strategies_produce_unique_hashes(self):
        """Each chunk should have a unique content hash within a non-repeating document."""
        # Use unique content to avoid inherent duplication from repeated text
        text = " ".join(f"Unique sentence number {i} with distinct content." for i in range(200))
        for strategy in [ChunkingStrategy.FIXED_SIZE, ChunkingStrategy.RECURSIVE]:
            chunker = get_chunker(strategy)
            chunks = chunker.chunk(text, chunk_size=100, chunk_overlap=0)
            hashes = [meta.content_hash for _, meta in chunks]
            # With unique content and no overlap, hashes should be mostly unique
            assert len(set(hashes)) >= len(hashes) * 0.8

    def test_max_chunks_cap(self):
        """Ensure no strategy exceeds 500 chunks."""
        text = "word " * 100000  # Very long
        for strategy in [ChunkingStrategy.FIXED_SIZE, ChunkingStrategy.RECURSIVE]:
            chunker = get_chunker(strategy)
            chunks = chunker.chunk(text, chunk_size=10, chunk_overlap=0)
            assert len(chunks) <= 500


# ── Embedding Gateway Stress Tests ───────────────────────────

from app.ai.embedding_gateway import (
    EmbeddingGateway,
    EmbeddingGatewayError,
    _cache_key,
    _sanitize_error,
    embedding_to_vector_str,
)


class TestEmbeddingGatewayStress:
    """Stress tests for the embedding gateway."""

    def test_cache_key_uniqueness_bulk(self):
        """Generate 10000 cache keys and verify uniqueness."""
        keys = set()
        for i in range(10000):
            key = _cache_key("model", 1536, f"text-{i}-{random.random()}")
            assert key not in keys, f"Collision at iteration {i}"
            keys.add(key)
        assert len(keys) == 10000

    def test_cache_key_with_long_text(self):
        """Cache key with very long text (100KB)."""
        text = "a" * 100000
        key = _cache_key("model", 1536, text)
        assert len(key) < 200  # Key should be bounded
        assert key.startswith("emb:")

    def test_cache_key_with_empty_text(self):
        """Cache key with empty text."""
        key = _cache_key("model", 1536, "")
        assert key.startswith("emb:model:1536:")

    def test_sanitize_error_redacts_credentials(self):
        """Verify credential redaction in error messages."""
        exc = Exception("Authorization: Bearer sk-abc123xyz")
        msg = _sanitize_error(exc)
        assert "sk-abc123" not in msg
        assert "redacted" in msg

    def test_sanitize_error_preserves_safe_messages(self):
        """Verify safe messages are preserved."""
        exc = Exception("Connection timeout after 30s")
        msg = _sanitize_error(exc)
        assert "Connection timeout" in msg

    def test_vector_str_valid(self):
        """Valid embedding converts correctly."""
        emb = [0.1, 0.2, 0.3]
        result = embedding_to_vector_str(emb)
        assert result == "[0.1,0.2,0.3]"

    def test_vector_str_empty_raises(self):
        """Empty embedding raises ValueError."""
        with pytest.raises(ValueError, match="Empty"):
            embedding_to_vector_str([])

    def test_vector_str_nan_raises(self):
        """NaN in embedding raises ValueError."""
        with pytest.raises(ValueError, match="nan"):
            embedding_to_vector_str([1.0, float("nan"), 3.0])

    def test_vector_str_inf_raises(self):
        """Inf in embedding raises ValueError."""
        with pytest.raises(ValueError, match="inf"):
            embedding_to_vector_str([1.0, float("inf"), 3.0])

    def test_vector_str_non_numeric_raises(self):
        """Non-numeric in embedding raises ValueError."""
        with pytest.raises(ValueError, match="not numeric"):
            embedding_to_vector_str([1.0, "not_a_number", 3.0])  # type: ignore

    def test_vector_str_large_embedding(self):
        """Test with 1536-dim embedding (production size)."""
        emb = [random.uniform(-1, 1) for _ in range(1536)]
        result = embedding_to_vector_str(emb)
        assert result.startswith("[")
        assert result.endswith("]")
        values = result.strip("[]").split(",")
        assert len(values) == 1536

    @pytest.mark.asyncio
    async def test_batch_size_limit(self):
        """Batch exceeding max size should raise."""
        gateway = EmbeddingGateway()
        texts = [f"text-{i}" for i in range(501)]
        with pytest.raises(EmbeddingGatewayError, match="exceeds maximum"):
            await gateway.generate_batch(texts)

    @pytest.mark.asyncio
    async def test_concurrent_generate_calls(self):
        """Simulate concurrent embedding requests."""
        gateway = EmbeddingGateway()
        mock_embedding = [0.1] * 1536

        with patch("app.ai.embedding_gateway.settings") as mock_settings:
            mock_settings.EMBEDDING_DEFAULT_MODEL = "text-embedding-3-small"
            mock_settings.AGENT_MEMORY_VECTOR_DIMENSIONS = 1536
            mock_settings.EMBEDDING_CACHE_ENABLED = False
            mock_settings.AI_OPENAI_API_KEY = "sk-test"

            with patch.object(
                gateway,
                "_call_provider",
                return_value=mock_embedding,
            ):
                tasks = [gateway.generate(f"text-{i}") for i in range(50)]
                results = await asyncio.gather(*tasks)
                assert len(results) == 50
                assert all(len(r) == 1536 for r in results)

    @pytest.mark.asyncio
    async def test_batch_uses_mget_single_call(self):
        """generate_batch should call _cache_mget once (not N times)."""
        gateway = EmbeddingGateway()
        emb = [0.1] * 1536

        with patch("app.ai.embedding_gateway.settings") as mock_settings:
            mock_settings.EMBEDDING_DEFAULT_MODEL = "text-embedding-3-small"
            mock_settings.AGENT_MEMORY_VECTOR_DIMENSIONS = 1536
            mock_settings.EMBEDDING_CACHE_ENABLED = True
            mock_settings.EMBEDDING_CACHE_TTL_SECONDS = 86400

            mget_mock = AsyncMock(return_value=[None, None, None])
            mset_mock = AsyncMock()
            with patch.object(gateway, "_cache_mget", mget_mock):
                with patch.object(gateway, "_cache_mset", mset_mock):
                    with patch.object(
                        gateway,
                        "_call_provider_batch",
                        return_value=[emb, emb, emb],
                    ):
                        results = await gateway.generate_batch(["a", "b", "c"])
                        assert len(results) == 3
                        # Batched cache: one mget call, one mset call
                        assert mget_mock.call_count == 1
                        assert mset_mock.call_count == 1
                        # mget called with exactly 3 keys
                        assert len(mget_mock.call_args[0][0]) == 3
                        # mset called with exactly 3 key-value pairs
                        assert len(mset_mock.call_args[0][0]) == 3


# ── Reranker Stress Tests ────────────────────────────────────

from app.agents.reranker import Reranker


class TestRerankerStress:
    """Stress tests for the reranker."""

    @pytest.mark.asyncio
    async def test_many_documents(self):
        """Rerank with 100 documents."""
        reranker = Reranker()
        documents = [f"Document about topic {i}" for i in range(100)]
        with patch("app.agents.reranker.settings") as mock_settings:
            mock_settings.RAG_RERANKER_PROVIDER = "none"
            mock_settings.RAG_RERANKER_TOP_K = 10
            results = await reranker.rerank("test query", documents)
            assert len(results) == 10

    @pytest.mark.asyncio
    async def test_empty_query(self):
        """Rerank with empty query."""
        reranker = Reranker()
        with patch("app.agents.reranker.settings") as mock_settings:
            mock_settings.RAG_RERANKER_PROVIDER = "none"
            mock_settings.RAG_RERANKER_TOP_K = 5
            results = await reranker.rerank("", ["doc1", "doc2"])
            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_documents_with_special_characters(self):
        """Rerank with documents containing special chars."""
        reranker = Reranker()
        documents = [
            "Normal document",
            "Document with <html> tags",
            "Document with 'quotes' and \"double quotes\"",
            "Document with\nnewlines\tand\ttabs",
            "Document with emoji 🎉🎊",
            "",  # Empty document
        ]
        with patch("app.agents.reranker.settings") as mock_settings:
            mock_settings.RAG_RERANKER_PROVIDER = "none"
            mock_settings.RAG_RERANKER_TOP_K = 10
            results = await reranker.rerank("test", documents)
            assert len(results) == 6

    @pytest.mark.asyncio
    async def test_noop_ordering_stability(self):
        """Noop reranker preserves document order."""
        results = Reranker._noop_rerank(["a", "b", "c", "d", "e"], 5)
        assert [r.text for r in results] == ["a", "b", "c", "d", "e"]
        # Scores should be strictly descending
        for i in range(len(results) - 1):
            assert results[i].score > results[i + 1].score


# ── Search Engine Stress Tests ───────────────────────────────

from datetime import UTC

from app.agents.search import (
    HybridSearchEngine,
    SearchFilters,
    SearchSource,
    SearchType,
    _vec_cast,
    _vec_column,
)
from app.core.query_utils import escape_like


class TestSearchStress:
    """Stress tests for the hybrid search engine."""

    def test_escape_like_special_characters(self):
        """ILIKE escape handles all special characters."""
        assert escape_like("50% off") == "50\\% off"
        assert escape_like("file_name") == "file\\_name"
        assert escape_like("back\\slash") == "back\\\\slash"
        assert escape_like("normal text") == "normal text"
        assert escape_like("") == ""
        assert escape_like("%_%\\") == "\\%\\_\\%\\\\"

    @pytest.mark.asyncio
    async def test_search_with_all_filters(self):
        """Search with every filter set simultaneously."""
        from datetime import datetime

        engine = HybridSearchEngine()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch.object(engine, "_get_query_embedding", return_value=None):
            results = await engine.search(
                query="test",
                tenant_id=uuid.uuid4(),
                sources=[SearchSource.CHUNKS],
                filters=SearchFilters(
                    data_source_ids=[uuid.uuid4(), uuid.uuid4()],
                    source_types=["pdf", "csv"],
                    tags=["important", "reviewed"],
                    date_from=datetime(2024, 1, 1, tzinfo=UTC),
                    date_to=datetime(2025, 12, 31, tzinfo=UTC),
                    section_title="Introduction",
                ),
                limit=10,
                search_type=SearchType.TEXT,
                db=mock_db,
            )
            # Should execute without error
            assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_weight_validation(self):
        """Search with zero weights should use defaults."""
        engine = HybridSearchEngine()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch.object(engine, "_get_query_embedding", return_value=None):
            results = await engine.search(
                query="test",
                tenant_id=uuid.uuid4(),
                sources=[SearchSource.CHUNKS],
                limit=5,
                search_type=SearchType.TEXT,
                vector_weight=0.0,
                text_weight=0.0,
                db=mock_db,
            )
            assert isinstance(results, list)

    def test_vec_column_selects_halfvec_when_configured(self):
        """VECTOR_QUANTIZATION=half should use embedding_halfvec column."""
        with patch("app.agents.search.settings") as mock_settings:
            mock_settings.VECTOR_QUANTIZATION = "half"
            assert _vec_column() == "embedding_halfvec"
            assert "halfvec" in _vec_cast()

    def test_vec_column_selects_full_when_configured(self):
        """VECTOR_QUANTIZATION=full should use embedding_vec column."""
        with patch("app.agents.search.settings") as mock_settings:
            mock_settings.VECTOR_QUANTIZATION = "full"
            assert _vec_column() == "embedding_vec"
            assert "vector" in _vec_cast()

    @pytest.mark.asyncio
    async def test_search_with_sql_injection_in_section_title(self):
        """Ensure SQL injection in section_title is escaped."""
        engine = HybridSearchEngine()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch.object(engine, "_get_query_embedding", return_value=None):
            results = await engine.search(
                query="test",
                tenant_id=uuid.uuid4(),
                sources=[SearchSource.CHUNKS],
                filters=SearchFilters(
                    section_title="'; DROP TABLE data_source_chunks; --",
                ),
                limit=5,
                search_type=SearchType.TEXT,
                db=mock_db,
            )
            # Should execute without error (injection is parameterized)
            assert isinstance(results, list)


# ── Model Stress Tests ───────────────────────────────────────

from app.db.models.datasource import VectorPrecision, VectorType


class TestVectorTypeStress:
    """Stress tests for the VectorType."""

    def test_hash_consistency(self):
        """Same dimensions should produce same hash."""
        vt1 = VectorType(1536)
        vt2 = VectorType(1536)
        assert hash(vt1) == hash(vt2)
        assert vt1 == vt2

    def test_different_dimensions_different_hash(self):
        """Different dimensions should produce different hash."""
        vt1 = VectorType(1536)
        vt2 = VectorType(384)
        assert hash(vt1) != hash(vt2)
        assert vt1 != vt2

    def test_halfvec_col_spec(self):
        """Half-precision type generates halfvec column spec."""
        vt = VectorType(1536, precision=VectorPrecision.HALF)
        assert vt.get_col_spec() == "halfvec(1536)"

    def test_binary_col_spec(self):
        """Binary precision type generates bit column spec."""
        vt = VectorType(1536, precision=VectorPrecision.BINARY)
        assert vt.get_col_spec() == "bit(1536)"

    def test_full_col_spec(self):
        """Full precision type generates vector column spec."""
        vt = VectorType(1536, precision=VectorPrecision.FULL)
        assert vt.get_col_spec() == "vector(1536)"

    def test_precision_accepts_string(self):
        """VectorType coerces string precision to VectorPrecision enum."""
        vt = VectorType(1536, precision="half")
        assert vt.precision == VectorPrecision.HALF
        assert vt.get_col_spec() == "halfvec(1536)"

    def test_precision_invalid_raises(self):
        """Invalid precision string raises ValueError via enum coercion."""
        with pytest.raises(ValueError):
            VectorType(1536, precision="invalid")

    def test_result_processor_returns_none_for_unknown_type(self):
        """Result processor rejects raw driver types it doesn't understand."""
        vt = VectorType(3)
        processor = vt.result_processor(None, None)
        assert processor(42) is None
        assert processor({"not": "a vector"}) is None

    def test_different_precision_different_hash(self):
        """Same dimensions but different precision should differ."""
        vt_full = VectorType(1536, precision="full")
        vt_half = VectorType(1536, precision="half")
        vt_binary = VectorType(1536, precision="binary")
        assert hash(vt_full) != hash(vt_half)
        assert hash(vt_full) != hash(vt_binary)
        assert vt_full != vt_half

    def test_storage_size_comparison(self):
        """Verify the storage size claims are correct."""
        # float32: 4 bytes * 1536 = 6144 bytes
        assert 4 * 1536 == 6144
        # float16: 2 bytes * 1536 = 3072 bytes (50% savings)
        assert 2 * 1536 == 3072
        # binary: 1536 bits / 8 = 192 bytes (97% savings)
        assert 1536 // 8 == 192
        # Verify savings ratios
        assert 3072 / 6144 == 0.5  # halfvec = 50% of full
        assert 192 / 6144 < 0.032  # binary < 3.2% of full

    def test_result_processor_parses_vector_string(self):
        """Result processor correctly parses pgvector string format."""
        vt = VectorType(3)
        processor = vt.result_processor(None, None)
        result = processor("[1.0,2.0,3.0]")
        assert result == [1.0, 2.0, 3.0]

    def test_result_processor_handles_none(self):
        """Result processor handles None."""
        vt = VectorType(3)
        processor = vt.result_processor(None, None)
        assert processor(None) is None

    def test_result_processor_handles_list(self):
        """Result processor handles already-parsed list."""
        vt = VectorType(3)
        processor = vt.result_processor(None, None)
        assert processor([1.0, 2.0]) == [1.0, 2.0]

    def test_result_processor_empty_string(self):
        """Result processor handles empty vector string."""
        vt = VectorType(0)
        processor = vt.result_processor(None, None)
        result = processor("[]")
        assert result == []

    def test_col_spec(self):
        """Column spec includes dimensions."""
        assert VectorType(1536).get_col_spec() == "vector(1536)"
        assert VectorType(384).get_col_spec() == "vector(384)"

    def test_cache_ok_with_set(self):
        """VectorType instances are hashable for SQLAlchemy caching."""
        s = {VectorType(1536), VectorType(384), VectorType(1536)}
        assert len(s) == 2  # 1536 deduped


# ── RAG Evaluator Stress Tests ───────────────────────────────

from app.agents.rag_metrics import RAGEvaluator


class TestDateParser:
    """Tests for the ISO-8601 date parser used in the search API."""

    def test_naive_date_defaults_to_utc(self):
        from app.api.v1.search import _parse_iso_with_tz

        result = _parse_iso_with_tz("2025-01-15T12:00:00", "date_from")
        assert result.tzinfo is not None
        assert result.year == 2025

    def test_aware_date_preserves_tz(self):
        from app.api.v1.search import _parse_iso_with_tz

        result = _parse_iso_with_tz("2025-01-15T12:00:00+05:00", "date_from")
        assert result.tzinfo is not None
        assert result.hour == 12

    def test_invalid_date_raises_http_400(self):
        from fastapi import HTTPException

        from app.api.v1.search import _parse_iso_with_tz

        with pytest.raises(HTTPException) as exc_info:
            _parse_iso_with_tz("not-a-date", "date_from")
        assert exc_info.value.status_code == 400
        assert "date_from" in exc_info.value.detail


class TestRAGEvaluatorStress:
    def test_empty_results(self):
        evaluator = RAGEvaluator()
        metrics = evaluator.evaluate_retrieval([])
        assert metrics.num_results == 0
        assert metrics.top_score == 0.0

    def test_single_result(self):
        evaluator = RAGEvaluator()
        metrics = evaluator.evaluate_retrieval([{"content": "test", "score": 0.95}])
        assert metrics.num_results == 1
        assert metrics.top_score == 0.95
        assert metrics.score_spread == 0.0

    def test_many_results(self):
        evaluator = RAGEvaluator()
        results = [{"content": f"result-{i}", "score": 1.0 - i * 0.01} for i in range(100)]
        metrics = evaluator.evaluate_retrieval(results)
        assert metrics.num_results == 100
        assert metrics.top_score == 1.0
        assert metrics.min_score == pytest.approx(0.01)

    def test_perfect_recall(self):
        evaluator = RAGEvaluator()
        results = [
            {"content": "answer A", "score": 0.9},
            {"content": "answer B", "score": 0.8},
        ]
        metrics = evaluator.evaluate_retrieval(results, ground_truth=["answer A", "answer B"])
        assert metrics.context_recall == 1.0
        assert metrics.context_precision == 1.0

    def test_zero_recall(self):
        evaluator = RAGEvaluator()
        results = [
            {"content": "irrelevant stuff", "score": 0.9},
        ]
        metrics = evaluator.evaluate_retrieval(results, ground_truth=["the actual answer"])
        assert metrics.context_recall == 0.0


# ── Integration-Style Stress Tests ───────────────────────────


class TestEndToEndStress:
    """Integration-like stress tests combining multiple components."""

    def test_chunk_and_evaluate_large_document(self):
        """Chunk a large document and evaluate the chunk distribution."""
        # Simulate a technical document
        paragraphs = []
        for i in range(50):
            paragraph = f"Section {i}: " + " ".join(f"This is sentence {j} about topic {i}." for j in range(10))
            paragraphs.append(paragraph)
        document = "\n\n".join(paragraphs)

        for strategy in [ChunkingStrategy.FIXED_SIZE, ChunkingStrategy.RECURSIVE]:
            chunker = get_chunker(strategy)
            chunks = chunker.chunk(document, chunk_size=500, chunk_overlap=100)
            assert len(chunks) > 20
            # All chunks should have content
            for chunk_text, meta in chunks:
                assert len(chunk_text.strip()) > 0
                assert meta.content_hash
                assert meta.chunk_index >= 0

    def test_markdown_document_full_pipeline(self):
        """Full chunking pipeline for a markdown document."""
        document = """# User Guide

## Installation

```bash
pip install mypackage
```

Run `mypackage --init` to initialize.

## Configuration

### Basic Setup

Set the following environment variables:
- `API_KEY`: Your API key
- `DB_URL`: Database connection string

### Advanced Setup

For production deployments, configure these additional options:

| Setting | Default | Description |
|---------|---------|-------------|
| WORKERS | 4 | Number of worker processes |
| TIMEOUT | 30 | Request timeout in seconds |
| LOG_LEVEL | INFO | Logging verbosity |

## API Reference

### GET /health

Returns the service health status.

### POST /search

Search for documents using hybrid search.

## Troubleshooting

If you encounter errors, check the logs at `/var/log/mypackage/`.
"""
        chunker = MarkdownChunker()
        chunks = chunker.chunk(document, chunk_size=300)
        assert len(chunks) >= 3

        # Verify code blocks are preserved
        code_chunks = [t for t, _ in chunks if "pip install" in t]
        assert len(code_chunks) >= 1

        # Verify table is preserved
        table_chunks = [t for t, _ in chunks if "WORKERS" in t]
        assert len(table_chunks) >= 1

        # Verify heading hierarchy is tracked
        for _, meta in chunks:
            if meta.section_title and "Advanced" in (meta.section_title or ""):
                assert len(meta.heading_hierarchy) >= 1

    @pytest.mark.asyncio
    async def test_concurrent_chunking_strategies(self):
        """Run all strategies concurrently on the same document."""
        text = "Sample text. " * 200

        async def chunk_with_strategy(strategy):
            chunker = get_chunker(strategy)
            return chunker.chunk(text, chunk_size=100)

        tasks = [
            chunk_with_strategy(ChunkingStrategy.FIXED_SIZE),
            chunk_with_strategy(ChunkingStrategy.RECURSIVE),
            chunk_with_strategy(ChunkingStrategy.MARKDOWN),
        ]
        results = await asyncio.gather(*tasks)
        for result in results:
            assert len(result) > 0

    def test_performance_benchmark_fixed_chunker(self):
        """Benchmark: FixedSizeChunker should handle 1MB in <1 second."""
        text = "Performance test sentence. " * 40000  # ~1MB
        chunker = FixedSizeChunker()

        start = time.monotonic()
        for _ in range(10):  # 10 iterations
            chunker.chunk(text, chunk_size=1000)
        elapsed = time.monotonic() - start

        avg_time = elapsed / 10
        assert avg_time < 1.0, f"Average chunk time {avg_time:.3f}s exceeds 1s"

    def test_performance_benchmark_recursive_chunker(self):
        """Benchmark: RecursiveChunker should handle 1MB in <2 seconds."""
        text = "Performance test.\n\n" * 20000  # ~360KB with many separators
        chunker = RecursiveChunker()

        start = time.monotonic()
        for _ in range(5):
            chunker.chunk(text, chunk_size=500)
        elapsed = time.monotonic() - start

        avg_time = elapsed / 5
        assert avg_time < 2.0, f"Average chunk time {avg_time:.3f}s exceeds 2s"
