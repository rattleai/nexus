"""Multi-provider embedding gateway with caching and circuit breaker.

Mirrors the AIGateway pattern: provider abstraction, circuit breaker,
Prometheus metrics, and transparent Redis caching. Supports OpenAI,
Cohere, Voyage AI, and local embedding servers.
"""

from __future__ import annotations

import enum
import hashlib
import json
import math
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
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

embedding_breaker = CircuitBreaker("embedding", failure_threshold=5, recovery_timeout=120)

# Maximum batch size to prevent resource exhaustion
_MAX_BATCH_SIZE = 500

# Shared HTTP client (connection pooled, lazy-initialized)
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Get or create the shared async HTTP client with connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
    return _http_client


async def shutdown_http_client() -> None:
    """Close the shared HTTP client. Call during app shutdown."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


class EmbeddingProvider(enum.StrEnum):
    OPENAI = "openai"
    COHERE = "cohere"
    VOYAGE = "voyage"
    GOOGLE = "google"
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
    supports_matryoshka: bool = False


EMBEDDING_MODEL_CATALOG: dict[str, EmbeddingModelInfo] = {
    # ── OpenAI ────────────────────────────────────────────────
    "text-embedding-3-small": EmbeddingModelInfo(
        provider=EmbeddingProvider.OPENAI,
        model_name="text-embedding-3-small",
        display_name="OpenAI Embedding 3 Small",
        dimensions=1536,
        max_input_tokens=8191,
        supports_dimensions_param=True,
        supports_matryoshka=True,
    ),
    "text-embedding-3-large": EmbeddingModelInfo(
        provider=EmbeddingProvider.OPENAI,
        model_name="text-embedding-3-large",
        display_name="OpenAI Embedding 3 Large",
        dimensions=3072,
        max_input_tokens=8191,
        supports_dimensions_param=True,
        supports_matryoshka=True,
    ),
    # ── Cohere ────────────────────────────────────────────────
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
    "embed-v4.0": EmbeddingModelInfo(
        provider=EmbeddingProvider.COHERE,
        model_name="embed-v4.0",
        display_name="Cohere Embed v4 (Multimodal, native int8/binary)",
        dimensions=1024,
        max_input_tokens=512,
        supports_dimensions_param=True,
        supports_matryoshka=True,
    ),
    # ── Voyage AI ─────────────────────────────────────────────
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
    "voyage-4": EmbeddingModelInfo(
        provider=EmbeddingProvider.VOYAGE,
        model_name="voyage-4",
        display_name="Voyage 4 (MoE)",
        dimensions=1024,
        max_input_tokens=32000,
        supports_dimensions_param=True,
        supports_matryoshka=True,
    ),
    "voyage-4-large": EmbeddingModelInfo(
        provider=EmbeddingProvider.VOYAGE,
        model_name="voyage-4-large",
        display_name="Voyage 4 Large",
        dimensions=2048,
        max_input_tokens=32000,
        supports_dimensions_param=True,
        supports_matryoshka=True,
    ),
    # ── Google ────────────────────────────────────────────────
    "text-embedding-005": EmbeddingModelInfo(
        provider=EmbeddingProvider.GOOGLE,
        model_name="text-embedding-005",
        display_name="Google Text Embedding 005",
        dimensions=768,
        max_input_tokens=2048,
        supports_dimensions_param=True,
        supports_matryoshka=True,
    ),
    "gemini-embedding-001": EmbeddingModelInfo(
        provider=EmbeddingProvider.GOOGLE,
        model_name="gemini-embedding-001",
        display_name="Gemini Embedding (Highest MTEB)",
        dimensions=3072,
        max_input_tokens=8192,
        supports_dimensions_param=True,
        supports_matryoshka=True,
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
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    return f"emb:{model}:{dimensions}:{text_hash}"


def _sanitize_error(exc: Exception) -> str:
    """Sanitize exception messages to prevent API key leakage in logs."""
    msg = str(exc)
    for keyword in ("Authorization", "Bearer", "api_key", "apikey"):
        if keyword.lower() in msg.lower():
            return f"{type(exc).__name__}: [credentials redacted]"
    return msg


def embedding_to_vector_str(embedding: list[float]) -> str:
    """Convert embedding list to pgvector-compatible string format.

    Validates that all values are finite floats and the list is non-empty.
    Shared utility used by indexer.py and search.py to avoid duplication.
    """
    if not embedding:
        raise ValueError("Empty embedding vector")
    for i, v in enumerate(embedding):
        if not isinstance(v, (int, float)):
            raise ValueError(f"Embedding value at index {i} is not numeric: {type(v)}")
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"Embedding value at index {i} is {v}")
    return "[" + ",".join(str(v) for v in embedding) + "]"


class EmbeddingGateway:
    """Production-grade embedding gateway with caching, circuit breaker, and multi-provider support."""

    def _resolve_model_info(self, model: str | None) -> EmbeddingModelInfo:
        """Resolve model string to EmbeddingModelInfo."""
        model = model or settings.EMBEDDING_DEFAULT_MODEL
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
            EmbeddingProvider.GOOGLE: settings.AI_GOOGLE_API_KEY,
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
        dims = dimensions or min(settings.AGENT_MEMORY_VECTOR_DIMENSIONS, info.dimensions)

        if settings.EMBEDDING_CACHE_ENABLED:
            cached = await self._cache_get(info.model_name, dims, text)
            if cached is not None:
                return cached

        embedding = await self._call_provider(text, info, dims)

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

        if len(texts) > _MAX_BATCH_SIZE:
            raise EmbeddingGatewayError(
                f"Batch size {len(texts)} exceeds maximum {_MAX_BATCH_SIZE}",
                model=model or settings.EMBEDDING_DEFAULT_MODEL,
            )

        info = self._resolve_model_info(model)
        dims = dimensions or min(settings.AGENT_MEMORY_VECTOR_DIMENSIONS, info.dimensions)

        results: list[list[float] | None] = [None] * len(texts)
        miss_indices: list[int] = []

        if settings.EMBEDDING_CACHE_ENABLED:
            # Single MGET for all cache lookups instead of N sequential GETs
            cache_keys = [_cache_key(info.model_name, dims, t) for t in texts]
            cached_values = await self._cache_mget(cache_keys)
            for i, raw in enumerate(cached_values):
                if raw is not None:
                    results[i] = raw
                else:
                    miss_indices.append(i)
        else:
            miss_indices = list(range(len(texts)))

        if miss_indices:
            miss_texts = [texts[i] for i in miss_indices]
            embeddings = await self._call_provider_batch(miss_texts, info, dims)
            for idx, embedding in zip(miss_indices, embeddings):
                results[idx] = embedding

            if settings.EMBEDDING_CACHE_ENABLED:
                # Single pipelined SET for all misses instead of N sequential SETs
                miss_map = {
                    _cache_key(info.model_name, dims, texts[idx]): embeddings[j]
                    for j, idx in enumerate(miss_indices)
                }
                await self._cache_mset(miss_map)

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
            embedding_breaker.record_failure(breaker_key)
            EMBEDDING_REQUESTS_TOTAL.labels(
                provider=info.provider.value, model=info.model_name, status="error",
            ).inc()
            raise
        except Exception as exc:
            embedding_breaker.record_failure(breaker_key)
            EMBEDDING_REQUESTS_TOTAL.labels(
                provider=info.provider.value, model=info.model_name, status="error",
            ).inc()
            raise EmbeddingGatewayError(
                f"Embedding generation failed: {_sanitize_error(exc)}",
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
            embedding_breaker.record_failure(breaker_key)
            EMBEDDING_REQUESTS_TOTAL.labels(
                provider=info.provider.value, model=info.model_name, status="error",
            ).inc()
            raise
        except Exception as exc:
            embedding_breaker.record_failure(breaker_key)
            EMBEDDING_REQUESTS_TOTAL.labels(
                provider=info.provider.value, model=info.model_name, status="error",
            ).inc()
            raise EmbeddingGatewayError(
                f"Batch embedding generation failed: {_sanitize_error(exc)}",
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
            EmbeddingProvider.GOOGLE: self._generate_google,
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

        client = _get_http_client()
        response = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        try:
            data = response.json()
            usage = data.get("usage", {})
            EMBEDDING_TOKENS_TOTAL.labels(
                provider="openai", model=info.model_name,
            ).inc(usage.get("total_tokens", 0))
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise EmbeddingGatewayError(
                f"Unexpected response from OpenAI embedding API",
                provider="openai",
                model=info.model_name,
            ) from exc

    async def _generate_cohere(
        self, texts: list[str], info: EmbeddingModelInfo, dimensions: int,
    ) -> list[list[float]]:
        """Generate embeddings via Cohere API.

        For embed-v4.0+, supports native int8/binary quantization and MRL
        dimensionality reduction via output_dimension parameter.
        """
        api_key = self._resolve_api_key(EmbeddingProvider.COHERE)
        truncated = [t[:2048] for t in texts]

        body: dict[str, Any] = {
            "texts": truncated,
            "model": info.model_name,
            "input_type": "search_document",
            "embedding_types": ["float"],
        }
        # MRL: forward output_dimension for Matryoshka-capable models (embed-v4.0+)
        if info.supports_dimensions_param and dimensions < info.dimensions:
            body["output_dimension"] = dimensions

        client = _get_http_client()
        response = await client.post(
            "https://api.cohere.com/v2/embed",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        try:
            data = response.json()
            return data["embeddings"]["float"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise EmbeddingGatewayError(
                f"Unexpected response from Cohere embedding API",
                provider="cohere",
                model=info.model_name,
            ) from exc

    async def _generate_voyage(
        self, texts: list[str], info: EmbeddingModelInfo, dimensions: int,
    ) -> list[list[float]]:
        """Generate embeddings via Voyage AI API.

        For Matryoshka-capable models (voyage-4, voyage-4-large), supports
        output_dimension parameter for reduced dimensionality.
        """
        api_key = self._resolve_api_key(EmbeddingProvider.VOYAGE)
        truncated = [t[:32000] for t in texts]

        body: dict[str, Any] = {
            "input": truncated,
            "model": info.model_name,
        }
        # MRL: forward output_dimension for Matryoshka-capable models
        if info.supports_matryoshka and dimensions < info.dimensions:
            body["output_dimension"] = dimensions

        client = _get_http_client()
        response = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        try:
            data = response.json()
            sorted_data = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise EmbeddingGatewayError(
                f"Unexpected response from Voyage embedding API",
                provider="voyage",
                model=info.model_name,
            ) from exc

    async def _generate_google(
        self, texts: list[str], info: EmbeddingModelInfo, dimensions: int,
    ) -> list[list[float]]:
        """Generate embeddings via Google Generative AI API."""
        api_key = self._resolve_api_key(EmbeddingProvider.GOOGLE)
        truncated = [t[:8192] for t in texts]

        # Google's batch embedding endpoint accepts multiple content items
        requests_body = [
            {"model": f"models/{info.model_name}", "content": {"parts": [{"text": t}]}}
            for t in truncated
        ]

        body: dict[str, Any] = {"requests": requests_body}

        client = _get_http_client()
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{info.model_name}:batchEmbedContents",
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json=body,
        )
        response.raise_for_status()
        try:
            data = response.json()
            return [item["values"] for item in data["embeddings"]]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise EmbeddingGatewayError(
                "Unexpected response from Google embedding API",
                provider="google",
                model=info.model_name,
            ) from exc

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

        client = _get_http_client()
        response = await client.post(
            f"{base_url.rstrip('/')}/embeddings",
            json={
                "input": texts,
                "model": info.model_name,
            },
        )
        response.raise_for_status()
        try:
            data = response.json()
            if isinstance(data, list):
                return data
            sorted_data = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in sorted_data]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise EmbeddingGatewayError(
                f"Unexpected response from local embedding server",
                provider="local",
                model=info.model_name,
            ) from exc

    # ── Cache operations ──────────────────────────────────────

    async def _cache_get(self, model: str, dimensions: int, text: str) -> list[float] | None:
        """Try to get an embedding from Redis cache."""
        key = _cache_key(model, dimensions, text)
        try:
            raw = await redis_pool.get(key)
            if raw is not None:
                EMBEDDING_CACHE_HITS_TOTAL.labels(model=model).inc()
                return json.loads(raw)
            EMBEDDING_CACHE_MISSES_TOTAL.labels(model=model).inc()
        except json.JSONDecodeError:
            logger.warning("embedding_cache_corrupted_value", model=model)
        except Exception:
            logger.warning("embedding_cache_get_error", exc_info=True)
        return None

    async def _cache_mget(self, keys: list[str]) -> list[list[float] | None]:
        """Batch cache lookup via Redis MGET. Returns parallel list of results."""
        if not keys:
            return []
        try:
            raws = await redis_pool.mget(keys)
        except Exception:
            logger.warning("embedding_cache_mget_error", exc_info=True)
            return [None] * len(keys)

        results: list[list[float] | None] = []
        hits = 0
        for raw in raws:
            if raw is None:
                results.append(None)
                continue
            try:
                results.append(json.loads(raw))
                hits += 1
            except json.JSONDecodeError:
                logger.warning("embedding_cache_corrupted_value")
                results.append(None)

        # Record aggregate hit/miss counts once per batch
        misses = len(keys) - hits
        model = settings.EMBEDDING_DEFAULT_MODEL
        if hits:
            EMBEDDING_CACHE_HITS_TOTAL.labels(model=model).inc(hits)
        if misses:
            EMBEDDING_CACHE_MISSES_TOTAL.labels(model=model).inc(misses)
        return results

    async def _cache_set(
        self, model: str, dimensions: int, text: str, embedding: list[float],
    ) -> None:
        """Store an embedding in Redis cache with TTL."""
        key = _cache_key(model, dimensions, text)
        try:
            await redis_pool.setex(
                key,
                settings.EMBEDDING_CACHE_TTL_SECONDS,
                json.dumps(embedding),
            )
        except Exception:
            logger.warning("embedding_cache_set_error", exc_info=True)

    async def _cache_mset(self, key_to_embedding: dict[str, list[float]]) -> None:
        """Batch cache write via Redis pipeline. Each key gets its own TTL."""
        if not key_to_embedding:
            return
        try:
            async with redis_pool.pipeline(transaction=False) as pipe:
                ttl = settings.EMBEDDING_CACHE_TTL_SECONDS
                for key, embedding in key_to_embedding.items():
                    pipe.setex(key, ttl, json.dumps(embedding))
                await pipe.execute()
        except Exception:
            logger.warning("embedding_cache_mset_error", exc_info=True)


# Module-level singleton
embedding_gateway = EmbeddingGateway()
