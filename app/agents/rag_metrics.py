"""RAG quality evaluation and metrics collection.

Provides retrieval quality evaluation functions that complement the
Prometheus metrics defined in app/ai/metrics.py. Used by the search
engine and RAG pipeline to track retrieval effectiveness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.stdlib.get_logger()


@dataclass
class RetrievalMetrics:
    """Computed metrics for a single retrieval operation."""

    num_results: int = 0
    top_score: float = 0.0
    mean_score: float = 0.0
    min_score: float = 0.0
    score_spread: float = 0.0
    context_recall: float | None = None
    context_precision: float | None = None


class RAGEvaluator:
    """Evaluates retrieval quality for observability and continuous improvement."""

    def evaluate_retrieval(
        self,
        results: list[dict[str, Any]],
        *,
        ground_truth: list[str] | None = None,
    ) -> RetrievalMetrics:
        """Compute retrieval quality metrics.

        Args:
            results: List of search results with 'content' and 'score' keys.
            ground_truth: Optional list of expected relevant texts for recall/precision.

        Returns:
            RetrievalMetrics with computed values.
        """
        if not results:
            return RetrievalMetrics()

        scores = [r.get("score", 0.0) for r in results]
        top_score = max(scores)
        min_score = min(scores)

        metrics = RetrievalMetrics(
            num_results=len(results),
            top_score=top_score,
            mean_score=sum(scores) / len(scores),
            min_score=min_score,
            score_spread=top_score - min_score,
        )

        if ground_truth:
            metrics.context_recall = self._compute_recall(results, ground_truth)
            metrics.context_precision = self._compute_precision(results, ground_truth)

        return metrics

    @staticmethod
    def _compute_recall(
        results: list[dict[str, Any]],
        ground_truth: list[str],
    ) -> float:
        """Compute context recall: fraction of relevant docs that were retrieved."""
        if not ground_truth:
            return 0.0

        retrieved_texts = {r.get("content", "") for r in results}
        hits = sum(1 for gt in ground_truth if any(gt in rt or rt in gt for rt in retrieved_texts))
        return hits / len(ground_truth)

    @staticmethod
    def _compute_precision(
        results: list[dict[str, Any]],
        ground_truth: list[str],
    ) -> float:
        """Compute context precision: fraction of retrieved docs that are relevant."""
        if not results:
            return 0.0

        hits = sum(
            1 for r in results if any(gt in r.get("content", "") or r.get("content", "") in gt for gt in ground_truth)
        )
        return hits / len(results)


# Module-level singleton
rag_evaluator = RAGEvaluator()
