"""Tests for hybrid search engine and search API."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.search import (
    HybridSearchEngine,
    SearchFilters,
    SearchResult,
    SearchSource,
    SearchType,
)


class TestSearchFilters:
    def test_defaults(self):
        f = SearchFilters()
        assert f.data_source_ids is None
        assert f.tags is None
        assert f.namespace == "rag"

    def test_custom_filters(self):
        ds_id = uuid.uuid4()
        f = SearchFilters(
            data_source_ids=[ds_id],
            source_types=["pdf"],
            tags=["important"],
        )
        assert f.data_source_ids == [ds_id]
        assert f.source_types == ["pdf"]
        assert f.tags == ["important"]


class TestSearchResult:
    def test_creation(self):
        r = SearchResult(
            id="test-id",
            content="test content",
            score=0.95,
            source=SearchSource.CHUNKS,
        )
        assert r.id == "test-id"
        assert r.score == 0.95
        assert r.source == SearchSource.CHUNKS


class TestHybridSearchEngine:
    @pytest.mark.asyncio
    async def test_search_with_no_embedding_falls_to_text(self):
        engine = HybridSearchEngine()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch.object(engine, "_get_query_embedding", return_value=None):
            results = await engine.search(
                query="test query",
                tenant_id=uuid.uuid4(),
                sources=[SearchSource.CHUNKS],
                limit=10,
                search_type=SearchType.HYBRID,
                db=mock_db,
            )
            assert results == []

    @pytest.mark.asyncio
    async def test_search_vector_only_no_embedding_returns_empty(self):
        engine = HybridSearchEngine()

        mock_db = AsyncMock()

        with patch.object(engine, "_get_query_embedding", return_value=None):
            results = await engine.search(
                query="test",
                tenant_id=uuid.uuid4(),
                sources=[SearchSource.CHUNKS],
                limit=5,
                search_type=SearchType.VECTOR,
                db=mock_db,
            )
            assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_limit(self):
        engine = HybridSearchEngine()
        mock_db = AsyncMock()
        embedding = [0.1] * 1536

        # Create mock results exceeding limit
        mock_rows = [
            {
                "id": uuid.uuid4(),
                "content": f"content {i}",
                "data_source_id": uuid.uuid4(),
                "section_title": None,
                "content_type": "pdf",
                "score": 0.9 - i * 0.1,
            }
            for i in range(10)
        ]
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = mock_rows
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch.object(engine, "_get_query_embedding", return_value=embedding):
            results = await engine.search(
                query="test",
                tenant_id=uuid.uuid4(),
                sources=[SearchSource.CHUNKS],
                limit=5,
                search_type=SearchType.VECTOR,
                db=mock_db,
            )
            assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_search_memory_disabled_returns_empty(self):
        engine = HybridSearchEngine()
        mock_db = AsyncMock()
        embedding = [0.1] * 1536

        with patch("app.agents.search.settings") as mock_settings:
            mock_settings.AGENT_MEMORY_VECTOR_ENABLED = False
            results = await engine._search_memory(
                query="test",
                query_embedding=embedding,
                tenant_id=uuid.uuid4(),
                filters=SearchFilters(),
                limit=10,
                search_type=SearchType.VECTOR,
                db=mock_db,
            )
            assert results == []


class TestSearchSource:
    def test_enum_values(self):
        assert SearchSource.CHUNKS == "chunks"
        assert SearchSource.MEMORY == "memory"


class TestSearchType:
    def test_enum_values(self):
        assert SearchType.VECTOR == "vector"
        assert SearchType.TEXT == "text"
        assert SearchType.HYBRID == "hybrid"
