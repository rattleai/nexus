"""Tests for the multi-provider embedding gateway."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.ai.embedding_gateway import (
    EMBEDDING_MODEL_CATALOG,
    EmbeddingGateway,
    EmbeddingGatewayError,
    EmbeddingProvider,
    _cache_key,
)


class TestEmbeddingModelCatalog:
    def test_catalog_has_openai_models(self):
        assert "text-embedding-3-small" in EMBEDDING_MODEL_CATALOG
        assert "text-embedding-3-large" in EMBEDDING_MODEL_CATALOG
        info = EMBEDDING_MODEL_CATALOG["text-embedding-3-small"]
        assert info.provider == EmbeddingProvider.OPENAI
        assert info.dimensions == 1536

    def test_catalog_has_cohere_models(self):
        assert "embed-english-v3.0" in EMBEDDING_MODEL_CATALOG
        info = EMBEDDING_MODEL_CATALOG["embed-english-v3.0"]
        assert info.provider == EmbeddingProvider.COHERE
        assert info.dimensions == 1024

    def test_catalog_has_voyage_models(self):
        assert "voyage-3" in EMBEDDING_MODEL_CATALOG
        info = EMBEDDING_MODEL_CATALOG["voyage-3"]
        assert info.provider == EmbeddingProvider.VOYAGE


class TestCacheKey:
    def test_cache_key_deterministic(self):
        key1 = _cache_key("model", 1536, "hello world")
        key2 = _cache_key("model", 1536, "hello world")
        assert key1 == key2

    def test_cache_key_different_for_different_text(self):
        key1 = _cache_key("model", 1536, "hello")
        key2 = _cache_key("model", 1536, "world")
        assert key1 != key2

    def test_cache_key_different_for_different_model(self):
        key1 = _cache_key("model-a", 1536, "hello")
        key2 = _cache_key("model-b", 1536, "hello")
        assert key1 != key2

    def test_cache_key_format(self):
        key = _cache_key("model", 1536, "hello")
        assert key.startswith("emb:model:1536:")


class TestEmbeddingGateway:
    @pytest.mark.asyncio
    async def test_generate_unknown_model_raises(self):
        gateway = EmbeddingGateway()
        with pytest.raises(EmbeddingGatewayError, match="Unknown embedding model"):
            await gateway.generate("test", model="nonexistent-model")

    @pytest.mark.asyncio
    async def test_generate_no_api_key_raises(self):
        gateway = EmbeddingGateway()
        with patch("app.ai.embedding_gateway.settings") as mock_settings:
            mock_settings.EMBEDDING_DEFAULT_MODEL = "embed-english-v3.0"
            mock_settings.AGENT_MEMORY_VECTOR_DIMENSIONS = 1536
            mock_settings.EMBEDDING_CACHE_ENABLED = False
            mock_settings.EMBEDDING_COHERE_API_KEY = ""
            with pytest.raises(EmbeddingGatewayError, match="No API key configured"):
                await gateway.generate("test", model="embed-english-v3.0")

    @pytest.mark.asyncio
    async def test_generate_with_cache_hit(self):
        gateway = EmbeddingGateway()
        cached_embedding = [0.1] * 1536

        with patch("app.ai.embedding_gateway.settings") as mock_settings:
            mock_settings.EMBEDDING_DEFAULT_MODEL = "text-embedding-3-small"
            mock_settings.AGENT_MEMORY_VECTOR_DIMENSIONS = 1536
            mock_settings.EMBEDDING_CACHE_ENABLED = True
            mock_settings.EMBEDDING_CACHE_TTL_SECONDS = 86400

            with patch.object(gateway, "_cache_get", return_value=cached_embedding) as mock_cache:
                result = await gateway.generate("test text")
                assert result == cached_embedding
                mock_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_batch_with_partial_cache(self):
        gateway = EmbeddingGateway()
        emb1 = [0.1] * 1536
        emb2 = [0.2] * 1536

        async def mock_mget(keys):
            # First key = text1 (hit), second = text2 (miss)
            return [emb1, None]

        with patch("app.ai.embedding_gateway.settings") as mock_settings:
            mock_settings.EMBEDDING_DEFAULT_MODEL = "text-embedding-3-small"
            mock_settings.AGENT_MEMORY_VECTOR_DIMENSIONS = 1536
            mock_settings.EMBEDDING_CACHE_ENABLED = True
            mock_settings.EMBEDDING_CACHE_TTL_SECONDS = 86400

            with patch.object(gateway, "_cache_mget", side_effect=mock_mget):
                with patch.object(gateway, "_cache_mset", new_callable=AsyncMock):
                    with patch.object(
                        gateway,
                        "_call_provider_batch",
                        return_value=[emb2],
                    ):
                        results = await gateway.generate_batch(["text1", "text2"])
                        assert results[0] == emb1  # From cache
                        assert results[1] == emb2  # From API

    @pytest.mark.asyncio
    async def test_generate_batch_empty_input(self):
        gateway = EmbeddingGateway()
        results = await gateway.generate_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_when_open(self):
        gateway = EmbeddingGateway()

        with patch("app.ai.embedding_gateway.settings") as mock_settings:
            mock_settings.EMBEDDING_DEFAULT_MODEL = "text-embedding-3-small"
            mock_settings.AGENT_MEMORY_VECTOR_DIMENSIONS = 1536
            mock_settings.EMBEDDING_CACHE_ENABLED = False
            mock_settings.AI_OPENAI_API_KEY = "sk-test"

            with patch("app.ai.embedding_gateway.embedding_breaker") as mock_breaker:
                mock_breaker.is_open.return_value = True
                with pytest.raises(EmbeddingGatewayError, match="circuit breaker is open"):
                    await gateway.generate("test")
