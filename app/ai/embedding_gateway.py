"""Multi-provider embedding gateway with caching and circuit breaker.

Mirrors the AIGateway pattern: provider abstraction, circuit breaker,
Prometheus metrics, and transparent Redis caching. Supports OpenAI,
Cohere, Voyage AI, and local embedding servers.
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from app.ai.metrics import (
    EMBEDDING_CACHE_HITS_TOTAL,
    EMBEDDING_CACHE_MISSES_TOTAL,
    EMBEDDING_LATENCY_SECONDS,
    EMBEDDING_REQUESTS_TOTAL,
    EMBEDDING_TOKENS_TOTAL,
)
from app.config import settings
from app.core.circuit_breaker import CircuitBreaker

logger = structlog.stdlib.get_logger()

embedding_breaker = CircuitBreaker("embedding", failure_threshold=5, recovery_timeout=120)


class EmbeddingProvider(enum.StrEnum):
    OPENAI = "openai"
    COHERE = "cohere"
    VOYAGE = "voyage"
    LOCAL = "local"


@dataclass(frozen=True)
class EmbeddingModelInfo:
    """Metadata for an embedding model."""

    provider: EmbeddingProvider
    model_name: str
    display_name: str
    dimensions: int
    max_input_tokens: int
    supports_batch: bool = True
    supports_dimensions_param: bool = False


EMBEDDING_MODEL_CATALOG: dict[str, EmbeddingModelInfo] = {
    # OpenAI
    "text-embedding-3-small": EmbeddingModelInfo(
        provider=EmbeddingProvider.OPENAI,
        model_name="text-embedding-3-small",
        display_name="OpenAI Embedding 3 Small",
        dimensions=1536,
        max_input_tokens=8191,
        supports_dimensions_param=True,
    ),
    "text-embedding-3-large": EmbeddingModelInfo(
        provider=EmbeddingProvider.OPENAI,
        model_name="text-embedding-3-large",
        display_name="OpenAI Embedding 3 Large",
        dimensions=3072,
        max_input_tokens=8191,
        supports_dimensions_param=True,
    ),
    # Cohere
    "embed-english-v3.0": EmbeddingModelInfo(
        provider=EmbeddingProvider.COHERE,
        model_name="embed-english-v3.0",
        display_name="Cohere Embed English v3",
        dimensions=1024,
        max_input_tokens=512,
    ),
    "embed-multilingual-v3.0": EmbeddingModelInfo(
        provider=EmbeddingProvider.COHERE,
        model_name="embed-multilingual-v3.0",
        display_name="Cohere Embed Multilingual v3",
        dimensions=1024,
        max_input_tokens=512,
    ),
    # Voyage AI
    "voyage-3": EmbeddingModelInfo(
        provider=EmbeddingProvider.VOYAGE,
        model_name="voyage-3",
        display_name="Voyage 3",
        dimensions=1024,
        max_input_tokens=32000,
    ),
    "voyage-3-lite": EmbeddingModelInfo(
        provider=EmbeddingProvider.VOYAGE,
        model_name="voyage-3-lite",
        display_name="Voyage 3 Lite",
        dimensions=512,
        max_input_tokens=32000,
    ),
}


class EmbeddingGatewayError(Exception):
    """Base exception for embedding gateway errors."""

    def __init__(self, message: str, *, provider: str = "", model: str = ""):
        self.provider = provider
        self.model = model
        super().__init__(message)


def _cache_key(model: str, dimensions: int, text: str) -> str:
    """Build a Redis cache key for an embedding."""
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:32]
    return f"emb:{model}:{dimensions}:{text_hash}"


class EmbeddingGateway:
    """Production-grade embedding gateway with caching, circuit breaker, and multi-provider support."""

    def __init__(self):
        self._default_model = settings.EMBEDDING_DEFAULT_MODEL
        self._default_dimensions = settings.AGENT_MEMORY_VECTOR_DIMENSIONS

    def _resolve_model_info(self, model: str | None) -> EmbeddingModelInfo:
        """Resolve model string to EmbeddingModelInfo."""
        model = model or self._default_model
        info = EMBEDDING_MODEL_CATALOG.get(model)
        if not info:
            raise EmbeddingGatewayError(f"Unknown embedding model: {model}", model=model)
        return info

    def _resolve_api_key(self, provider: EmbeddingProvider) -> str:
        """Resolve API key for the given provider."""
        key_map = {
            EmbeddingProvider.OPENAI: settings.AI_OPENAI_API_KEY,
            EmbeddingProvider.COHERE: settings.EMBEDDING_COHERE_API_KEY,
            EmbeddingProvider.VOYAGE: settings.EMBEDDING_VOYAGE_API_KEY,
        }
        key = key_map.get(provider, "")
        if not key and provider != EmbeddingProvider.LOCAL:
            raise EmbeddingGatewayError(
                f"No API key configured for embedding provider '{provider.value}'",
                provider=provider.value,
            )
        return key

    async def generate(
        self,
        text: str,
        *,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> list[float]:
        """Generate an embedding vector for the given text.

        Checks Redis cache first, falls back to provider API.
        """
        info = self._resolve_model_info(model)
        dims = dimensions or min(self._default_dimensions, info.dimensions)

        # Check cache
        if settings.EMBEDDING_CACHE_ENABLED:
            cached = await self._cache_get(info.model_name, dims, text)
            if cached is not None:
                return cached

        # Generate via provider
        embedding = await self._call_provider(text, info, dims)

        # Store in cache
        if settings.EMBEDDING_CACHE_ENABLED:
            await self._cache_set(info.model_name, dims, text, embedding)

        return embedding

    async def generate_batch(
        self,
        texts: list[str],
        *,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Checks cache for each text individually, only calls the API for misses.
        """
        if not texts:
            return []

        info = self._resolve_model_info(model)
        dims = dimensions or min(self._default_dimensions, info.dimensions)

        results: list[list[float] | None] = [None] * len(texts)
        miss_indices: list[int] = []

        # Check cache for each text
        if settings.EMBEDDING_CACHE_ENABLED:
            for i, text in enumerate(texts):
                cached = await self._cache_get(info.model_name, dims, text)
                if cached is not None:
                    results[i] = cached
                else:
                    miss_indices.append(i)
        else:
            miss_indices = list(range(len(texts)))

        # Call API for cache misses
        if miss_indices:
            miss_texts = [texts[i] for i in miss_indices]
            embeddings = await self._call_provider_batch(miss_texts, info, dims)
            for idx, embedding in zip(miss_indices, embeddings):
                results[idx] = embedding
                if settings.EMBEDDING_CACHE_ENABLED:
                    await self._cache_set(info.model_name, dims, texts[idx], embedding)

        return results  # type: ignore[return-value]

    # ── Provider implementations ─────────────────────────────

    async def _call_provider(
        self, text: str, info: EmbeddingModelInfo, dimensions: int,
    ) -> list[float]:
        """Route to the correct provider."""
        breaker_key = info.provider.value
        if embedding_breaker.is_open(breaker_key):
            raise EmbeddingGatewayError(
                f"Embedding provider '{info.provider.value}' circuit breaker is open",
                provider=info.provider.value,
                model=info.model_name,
            )

        start = time.monotonic()
        try:
            result = await self._dispatch(info.provider, [text], info, dimensions)
            embedding_breaker.record_success(breaker_key)
            elapsed = time.monotonic() - start
            EMBEDDING_LATENCY_SECONDS.labels(
                provider=info.provider.value, model=info.model_name,
            ).observe(elapsed)
            EMBEDDING_REQUESTS_TOTAL.labels(
                provider=info.provider.value, model=info.model_name, status="success",
            ).inc()
            return result[0]
        except EmbeddingGatewayError:
            raise
        except Exception as exc:
            embedding_breaker.record_failure(breaker_key)
            EMBEDDING_REQUESTS_TOTAL.labels(
                provider=info.provider.value, model=info.model_name, status="error",
            ).inc()
            raise EmbeddingGatewayError(
                f"Embedding generation failed: {exc}",
                provider=info.provider.value,
                model=info.model_name,
            ) from exc

    async def _call_provider_batch(
        self, texts: list[str], info: EmbeddingModelInfo, dimensions: int,
    ) -> list[list[float]]:
        """Route batch to the correct provider."""
        breaker_key = info.provider.value
        if embedding_breaker.is_open(breaker_key):
            raise EmbeddingGatewayError(
                f"Embedding provider '{info.provider.value}' circuit breaker is open",
                provider=info.provider.value,
                model=info.model_name,
            )

        start = time.monotonic()
        try:
            result = await self._dispatch(info.provider, texts, info, dimensions)
            embedding_breaker.record_success(breaker_key)
            elapsed = time.monotonic() - start
            EMBEDDING_LATENCY_SECONDS.labels(
                provider=info.provider.value, model=info.model_name,
            ).observe(elapsed)
            EMBEDDING_REQUESTS_TOTAL.labels(
                provider=info.provider.value, model=info.model_name, status="success",
            ).inc()
            return result
        except EmbeddingGatewayError:
            raise
        except Exception as exc:
            embedding_breaker.record_failure(breaker_key)
            EMBEDDING_REQUESTS_TOTAL.labels(
                provider=info.provider.value, model=info.model_name, status="error",
            ).inc()
            raise EmbeddingGatewayError(
                f"Batch embedding generation failed: {exc}",
                provider=info.provider.value,
                model=info.model_name,
            ) from exc

    async def _dispatch(
        self,
        provider: EmbeddingProvider,
        texts: list[str],
        info: EmbeddingModelInfo,
        dimensions: int,
    ) -> list[list[float]]:
        """Dispatch to the provider-specific implementation."""
        dispatch_map = {
            EmbeddingProvider.OPENAI: self._generate_openai,
            EmbeddingProvider.COHERE: self._generate_cohere,
            EmbeddingProvider.VOYAGE: self._generate_voyage,
            EmbeddingProvider.LOCAL: self._generate_local,
        }
        handler = dispatch_map.get(provider)
        if not handler:
            raise EmbeddingGatewayError(
                f"Unsupported embedding provider: {provider}",
                provider=provider.value,
            )
        return await handler(texts, info, dimensions)

    async def _generate_openai(
        self, texts: list[str], info: EmbeddingModelInfo, dimensions: int,
    ) -> list[list[float]]:
        """Generate embeddings via OpenAI API."""
        api_key = self._resolve_api_key(EmbeddingProvider.OPENAI)
        truncated = [t[:8192] for t in texts]

        body: dict[str, Any] = {
            "input": truncated,
            "model": info.model_name,
        }
        if info.supports_dimensions_param:
            body["dimensions"] = dimensions

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage", {})
            EMBEDDING_TOKENS_TOTAL.labels(
                provider="openai", model=info.model_name,
            ).inc(usage.get("total_tokens", 0))
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]

    async def _generate_cohere(
        self, texts: list[str], info: EmbeddingModelInfo, dimensions: int,
    ) -> list[list[float]]:
        """Generate embeddings via Cohere API."""
        api_key = self._resolve_api_key(EmbeddingProvider.COHERE)
        truncated = [t[:2048] for t in texts]

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.cohere.com/v2/embed",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "texts": truncated,
                    "model": info.model_name,
                    "input_type": "search_document",
                    "embedding_types": ["float"],
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["embeddings"]["float"]

    async def _generate_voyage(
        self, texts: list[str], info: EmbeddingModelInfo, dimensions: int,
    ) -> list[list[float]]:
        """Generate embeddings via Voyage AI API."""
        api_key = self._resolve_api_key(EmbeddingProvider.VOYAGE)
        truncated = [t[:32000] for t in texts]

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": truncated,
                    "model": info.model_name,
                },
            )
            response.raise_for_status()
            data = response.json()
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]

    async def _generate_local(
        self, texts: list[str], info: EmbeddingModelInfo, dimensions: int,
    ) -> list[list[float]]:
        """Generate embeddings via a local model server."""
        base_url = settings.EMBEDDING_LOCAL_URL
        if not base_url:
            raise EmbeddingGatewayError(
                "EMBEDDING_LOCAL_URL not configured",
                provider="local",
            )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/embeddings",
                json={
                    "input": texts,
                    "model": info.model_name,
                },
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return data
            sorted_data = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in sorted_data]

    # ── Cache operations ──────────────────────────────────────

    async def _cache_get(self, model: str, dimensions: int, text: str) -> list[float] | None:
        """Try to get an embedding from Redis cache."""
        try:
            from app.core.redis import redis_pool

            key = _cache_key(model, dimensions, text)
            raw = await redis_pool.get(key)
            if raw is not None:
                EMBEDDING_CACHE_HITS_TOTAL.labels(model=model).inc()
                return json.loads(raw)
            EMBEDDING_CACHE_MISSES_TOTAL.labels(model=model).inc()
        except Exception:
            logger.debug("embedding_cache_get_error", exc_info=True)
        return None

    async def _cache_set(
        self, model: str, dimensions: int, text: str, embedding: list[float],
    ) -> None:
        """Store an embedding in Redis cache with TTL."""
        try:
            from app.core.redis import redis_pool

            key = _cache_key(model, dimensions, text)
            await redis_pool.setex(
                key,
                settings.EMBEDDING_CACHE_TTL_SECONDS,
                json.dumps(embedding),
            )
        except Exception:
            logger.debug("embedding_cache_set_error", exc_info=True)


# Module-level singleton
embedding_gateway = EmbeddingGateway()
