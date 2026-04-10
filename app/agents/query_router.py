"""Query routing: classify queries and route to optimal retrieval strategies.

Routes queries to the best search configuration based on query type:
- FACTUAL: precise lookup → high vector weight (0.8)
- KEYWORD: known-term search → high text weight (0.8)
- ANALYTICAL: complex reasoning → hybrid, broader limit
- MULTI_PART: decompose into sub-queries, merge results

Uses regex-based classification by default (zero latency, zero cost).
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field

import structlog

logger = structlog.stdlib.get_logger()


class QueryCategory(enum.StrEnum):
    FACTUAL = "factual"
    KEYWORD = "keyword"
    ANALYTICAL = "analytical"
    MULTI_PART = "multi_part"


@dataclass
class QueryPlan:
    """Optimized search parameters based on query classification."""

    category: QueryCategory
    vector_weight: float = 0.6
    text_weight: float = 0.4
    limit_multiplier: float = 1.0
    sub_queries: list[str] = field(default_factory=list)


# Regex patterns for classification
_FACTUAL_PATTERNS = [
    re.compile(r"^(what|who|when|where|which)\s+(is|are|was|were)\b", re.I),
    re.compile(r"^(define|explain|describe)\s+", re.I),
    re.compile(r"^(how much|how many)\b", re.I),
]

_KEYWORD_PATTERNS = [
    re.compile(r"^[A-Z][A-Z0-9_\-]{2,}", re.I),  # Looks like an identifier/code
    re.compile(r"\b(error|exception|log|code|status)\s+\d+", re.I),
    re.compile(r"^[\"\']", re.I),  # Quoted term lookup
]

_ANALYTICAL_PATTERNS = [
    re.compile(r"\b(compare|difference|versus|vs\.?|between)\b", re.I),
    re.compile(r"\b(why|how does|how do|analyze|evaluate|assess)\b", re.I),
    re.compile(r"\b(pros and cons|advantages|disadvantages|trade.?off)\b", re.I),
]

_MULTI_PART_PATTERNS = [
    re.compile(r"\b(and also|additionally|furthermore|as well as)\b", re.I),
    re.compile(r"\?\s+(and|also|plus)\s+", re.I),
    re.compile(r"\d+\)\s+.+\d+\)\s+", re.I),  # Numbered sub-questions
]


class QueryRouter:
    """Classify queries and generate optimized search plans."""

    def route(self, query: str) -> QueryPlan:
        """Classify query and return optimal search parameters."""
        category = self._classify(query)

        plan = _CATEGORY_PLANS[category]

        logger.debug(
            "query_routed",
            category=category.value,
            vector_weight=plan.vector_weight,
            text_weight=plan.text_weight,
        )
        return plan

    def _classify(self, query: str) -> QueryCategory:
        """Classify query using regex patterns."""
        query = query.strip()

        # Check multi-part first (highest priority)
        for pattern in _MULTI_PART_PATTERNS:
            if pattern.search(query):
                return QueryCategory.MULTI_PART

        # Check analytical
        for pattern in _ANALYTICAL_PATTERNS:
            if pattern.search(query):
                return QueryCategory.ANALYTICAL

        # Check keyword
        for pattern in _KEYWORD_PATTERNS:
            if pattern.search(query):
                return QueryCategory.KEYWORD

        # Check factual
        for pattern in _FACTUAL_PATTERNS:
            if pattern.search(query):
                return QueryCategory.FACTUAL

        # Default to hybrid
        return QueryCategory.FACTUAL


_CATEGORY_PLANS: dict[QueryCategory, QueryPlan] = {
    QueryCategory.FACTUAL: QueryPlan(
        category=QueryCategory.FACTUAL,
        vector_weight=0.8,
        text_weight=0.2,
    ),
    QueryCategory.KEYWORD: QueryPlan(
        category=QueryCategory.KEYWORD,
        vector_weight=0.2,
        text_weight=0.8,
    ),
    QueryCategory.ANALYTICAL: QueryPlan(
        category=QueryCategory.ANALYTICAL,
        vector_weight=0.5,
        text_weight=0.5,
        limit_multiplier=1.5,
    ),
    QueryCategory.MULTI_PART: QueryPlan(
        category=QueryCategory.MULTI_PART,
        vector_weight=0.6,
        text_weight=0.4,
        limit_multiplier=2.0,
    ),
}


# Module-level singleton
query_router = QueryRouter()
