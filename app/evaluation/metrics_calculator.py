"""Pure IR metric computation for RAG evaluation.

Stateless, testable functions for computing standard information
retrieval quality metrics. Uses ID-based matching (not substring)
for deterministic, accurate evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class IRMetrics:
    """Computed IR metrics for a single query evaluation."""

    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg_at_k: float = 0.0
    k: int = 5


def precision_at_k(
    retrieved_ids: list[str],
    relevant_ids: set[str],
    k: int = 5,
) -> float:
    """Fraction of retrieved docs in top-k that are relevant.

    Args:
        retrieved_ids: Ordered list of retrieved document IDs.
        relevant_ids: Set of known-relevant document IDs.
        k: Cutoff position.

    Returns:
        Precision@k in [0, 1].
    """
    if not retrieved_ids or not relevant_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    relevant_in_top_k = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return relevant_in_top_k / len(top_k)


def recall_at_k(
    retrieved_ids: list[str],
    relevant_ids: set[str],
    k: int = 5,
) -> float:
    """Fraction of relevant docs that appear in top-k retrieved results.

    Args:
        retrieved_ids: Ordered list of retrieved document IDs.
        relevant_ids: Set of known-relevant document IDs.
        k: Cutoff position.

    Returns:
        Recall@k in [0, 1].
    """
    if not relevant_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    found = sum(1 for doc_id in top_k if doc_id in relevant_ids)
    return found / len(relevant_ids)


def mrr(
    retrieved_ids: list[str],
    relevant_ids: set[str],
) -> float:
    """Mean Reciprocal Rank: 1/position of the first relevant result.

    Args:
        retrieved_ids: Ordered list of retrieved document IDs.
        relevant_ids: Set of known-relevant document IDs.

    Returns:
        MRR in [0, 1]. 0 if no relevant doc found.
    """
    for i, doc_id in enumerate(retrieved_ids):
        if doc_id in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(
    retrieved_ids: list[str],
    relevance_grades: dict[str, int],
    k: int = 5,
) -> float:
    """Normalized Discounted Cumulative Gain at position k.

    Uses graded relevance scores (e.g., 0=irrelevant, 1=partially,
    2=highly relevant) with logarithmic position discounting.

    Args:
        retrieved_ids: Ordered list of retrieved document IDs.
        relevance_grades: Map of doc_id → relevance grade (higher = better).
        k: Cutoff position.

    Returns:
        NDCG@k in [0, 1].
    """
    if not retrieved_ids or not relevance_grades:
        return 0.0

    top_k = retrieved_ids[:k]

    # DCG: sum of relevance / log2(position + 1)
    dcg = 0.0
    for i, doc_id in enumerate(top_k):
        rel = relevance_grades.get(doc_id, 0)
        dcg += rel / math.log2(i + 2)  # +2 because positions are 1-indexed

    # Ideal DCG: sort all grades descending, compute DCG
    sorted_grades = sorted(relevance_grades.values(), reverse=True)[:k]
    idcg = 0.0
    for i, rel in enumerate(sorted_grades):
        idcg += rel / math.log2(i + 2)

    if idcg == 0:
        return 0.0
    return dcg / idcg


def compute_all(
    retrieved_ids: list[str],
    relevant_ids: set[str],
    relevance_grades: dict[str, int] | None = None,
    k: int = 5,
) -> IRMetrics:
    """Compute all IR metrics for a single query.

    Args:
        retrieved_ids: Ordered list of retrieved document IDs.
        relevant_ids: Set of known-relevant document IDs.
        relevance_grades: Optional graded relevance (for NDCG). If None,
            binary grades are derived from relevant_ids.
        k: Cutoff position for @k metrics.

    Returns:
        IRMetrics dataclass with all computed values.
    """
    if relevance_grades is None:
        relevance_grades = dict.fromkeys(relevant_ids, 1)

    return IRMetrics(
        precision_at_k=precision_at_k(retrieved_ids, relevant_ids, k),
        recall_at_k=recall_at_k(retrieved_ids, relevant_ids, k),
        mrr=mrr(retrieved_ids, relevant_ids),
        ndcg_at_k=ndcg_at_k(retrieved_ids, relevance_grades, k),
        k=k,
    )
