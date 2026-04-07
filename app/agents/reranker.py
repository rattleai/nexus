"""Pluggable re-ranking pipeline for RAG retrieval.

Re-rankers apply a second-stage precision pass on initial retrieval
results, using cross-encoder models or reranking APIs to reorder
candidates by relevance to the query.

Providers:
  - CohereReranker: Cohere Rerank API (rerank-v3.5)
  - CrossEncoderReranker: local cross-encoder model server
  - NoopReranker: passthrough (for when re-ranking is disabled)
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass

import httpx
import structlog

from app.ai.metrics import RAG_RERANK_LATENCY_SECONDS
from app.config import settings

logger = structlog.stdlib.get_logger()


class RerankerProvider(enum.StrEnum):
    COHERE = "cohere"
    CROSS_ENCODER = "cross_encoder"
    NONE = "none"


@dataclass
class RerankerResult:
    """A single re-ranked document."""

    index: int
    score: float
    text: str


class Reranker:
    """Re-rank documents by relevance to a query."""

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_k: int | None = None,
    ) -> list[RerankerResult]:
        """Re-rank documents and return top_k results sorted by relevance.

        Args:
            query: The search query.
            documents: List of document texts to re-rank.
            top_k: Number of top results to return (default from config).

        Returns:
            List of RerankerResult sorted by score descending.
        """
        top_k = top_k or settings.RAG_RERANKER_TOP_K

        provider = RerankerProvider(settings.RAG_RERANKER_PROVIDER)
        if provider == RerankerProvider.NONE or not documents:
            return self._noop_rerank(documents, top_k)

        start = time.monotonic()
        try:
            if provider == RerankerProvider.COHERE:
                results = await self._rerank_cohere(query, documents, top_k)
            elif provider == RerankerProvider.CROSS_ENCODER:
                results = await self._rerank_cross_encoder(query, documents, top_k)
            else:
                results = self._noop_rerank(documents, top_k)

            elapsed = time.monotonic() - start
            RAG_RERANK_LATENCY_SECONDS.labels(provider=provider.value).observe(elapsed)

            logger.info(
                "rerank_completed",
                provider=provider.value,
                input_docs=len(documents),
                output_docs=len(results),
                latency_ms=int(elapsed * 1000),
            )
            return results

        except (httpx.RequestError, httpx.HTTPStatusError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "rerank_failed",
                provider=provider.value,
                error=type(exc).__name__,
                exc_info=True,
            )
            return self._noop_rerank(documents, top_k)

    @staticmethod
    def _noop_rerank(documents: list[str], top_k: int) -> list[RerankerResult]:
        """Return documents in original order (no re-ranking)."""
        return [
            RerankerResult(index=i, score=1.0 - i * 0.01, text=doc)
            for i, doc in enumerate(documents[:top_k])
        ]

    async def _rerank_cohere(
        self, query: str, documents: list[str], top_k: int,
    ) -> list[RerankerResult]:
        """Re-rank via Cohere Rerank API."""
        api_key = settings.RAG_RERANKER_API_KEY
        if not api_key:
            raise ValueError("RAG_RERANKER_API_KEY not configured for Cohere reranker")

        model = settings.RAG_RERANKER_MODEL

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.cohere.com/v2/rerank",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "documents": documents,
                    "model": model,
                    "top_n": top_k,
                },
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("results", []):
                idx = item.get("index")
                if idx is None or not isinstance(idx, int) or not (0 <= idx < len(documents)):
                    logger.warning("rerank_invalid_index", idx=idx, max=len(documents))
                    continue
                results.append(RerankerResult(
                    index=idx,
                    score=item.get("relevance_score", 0.0),
                    text=documents[idx],
                ))
            return sorted(results, key=lambda r: r.score, reverse=True)

    async def _rerank_cross_encoder(
        self, query: str, documents: list[str], top_k: int,
    ) -> list[RerankerResult]:
        """Re-rank via a local cross-encoder model server."""
        base_url = settings.RAG_RERANKER_LOCAL_URL
        if not base_url:
            raise ValueError("RAG_RERANKER_LOCAL_URL not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/rerank",
                json={
                    "query": query,
                    "documents": documents,
                    "top_k": top_k,
                },
            )
            response.raise_for_status()
            data = response.json()

            results = []
            items = data.get("results", data if isinstance(data, list) else [])
            for item in items:
                if not isinstance(item, dict):
                    logger.warning("rerank_non_dict_result", item_type=type(item).__name__)
                    continue
                idx = item.get("index")
                if idx is None or not isinstance(idx, int) or not (0 <= idx < len(documents)):
                    logger.warning("rerank_invalid_index", idx=idx, max=len(documents))
                    continue
                results.append(RerankerResult(
                    index=idx,
                    score=item.get("score", item.get("relevance_score", 0.0)),
                    text=documents[idx],
                ))
            return sorted(results, key=lambda r: r.score, reverse=True)[:top_k]


# Module-level singleton
reranker = Reranker()
