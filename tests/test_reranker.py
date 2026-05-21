"""Tests for the re-ranking pipeline."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.reranker import Reranker, RerankerProvider, RerankerResult


class TestRerankerResult:
    def test_creation(self):
        r = RerankerResult(index=0, score=0.95, text="hello")
        assert r.index == 0
        assert r.score == 0.95
        assert r.text == "hello"


class TestReranker:
    @pytest.mark.asyncio
    async def test_noop_reranker(self):
        reranker = Reranker()
        with patch("app.agents.reranker.settings") as mock_settings:
            mock_settings.RAG_RERANKER_PROVIDER = "none"
            mock_settings.RAG_RERANKER_TOP_K = 3

            documents = ["doc1", "doc2", "doc3", "doc4"]
            results = await reranker.rerank("query", documents)
            assert len(results) == 3  # top_k=3
            assert results[0].text == "doc1"
            assert results[1].text == "doc2"

    @pytest.mark.asyncio
    async def test_empty_documents(self):
        reranker = Reranker()
        with patch("app.agents.reranker.settings") as mock_settings:
            mock_settings.RAG_RERANKER_PROVIDER = "cohere"
            mock_settings.RAG_RERANKER_TOP_K = 5

            results = await reranker.rerank("query", [])
            assert results == []

    @pytest.mark.asyncio
    async def test_cohere_reranker_no_key_falls_back(self):
        """When Cohere key is missing, should fall back to noop."""
        reranker = Reranker()
        with patch("app.agents.reranker.settings") as mock_settings:
            mock_settings.RAG_RERANKER_PROVIDER = "cohere"
            mock_settings.RAG_RERANKER_API_KEY = ""
            mock_settings.RAG_RERANKER_MODEL = "rerank-v3.5"
            mock_settings.RAG_RERANKER_TOP_K = 2

            results = await reranker.rerank("query", ["doc1", "doc2", "doc3"])
            # Falls back to noop on error
            assert len(results) == 2

    @pytest.mark.asyncio
    async def test_noop_scores_descending(self):
        results = Reranker._noop_rerank(["a", "b", "c"], 3)
        assert results[0].score > results[1].score
        assert results[1].score > results[2].score

    @pytest.mark.asyncio
    async def test_custom_top_k(self):
        reranker = Reranker()
        with patch("app.agents.reranker.settings") as mock_settings:
            mock_settings.RAG_RERANKER_PROVIDER = "none"
            mock_settings.RAG_RERANKER_TOP_K = 5

            documents = ["d1", "d2", "d3"]
            results = await reranker.rerank("query", documents, top_k=2)
            assert len(results) == 2


class TestRerankerProvider:
    def test_enum_values(self):
        assert RerankerProvider.COHERE == "cohere"
        assert RerankerProvider.CROSS_ENCODER == "cross_encoder"
        assert RerankerProvider.NONE == "none"
