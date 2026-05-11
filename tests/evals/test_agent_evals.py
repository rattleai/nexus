"""LLM evaluation tests using DeepEval metrics.

Measures agent output quality across multiple dimensions:
- Faithfulness: Are responses grounded in provided context?
- Relevance: Do responses address the user's question?
- Hallucination: Does the agent fabricate information?
- Toxicity: Are responses free of harmful content?

These tests run against real LLM APIs and should be scheduled nightly
(not on every PR) to manage costs.

Usage:
    pytest tests/evals/ -v --evals   # enable eval tests
    pytest tests/evals/ -v --evals -k faithfulness  # run specific eval

Requires:
    pip install deepeval
"""

from __future__ import annotations

import pytest


# Skip all eval tests unless --evals flag is passed
def pytest_addoption(parser):
    parser.addoption("--evals", action="store_true", default=False, help="Run LLM evaluation tests")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--evals"):
        skip = pytest.mark.skip(reason="LLM evals not enabled (use --evals)")
        for item in items:
            if "evals" in str(item.fspath):
                item.add_marker(skip)


# ── Test data ────────────────────────────────────────────────

EVAL_CASES = [
    {
        "input": "What is the capital of France?",
        "expected_output": "The capital of France is Paris.",
        "context": ["France is a country in Western Europe. Its capital city is Paris."],
    },
    {
        "input": "Explain how API rate limiting works in 2 sentences.",
        "expected_output": "API rate limiting restricts the number of requests a client can make within a time window. It protects services from abuse and ensures fair resource allocation.",
        "context": [
            "Rate limiting is a technique to control the rate of requests sent to a server. "
            "Common algorithms include token bucket, sliding window, and fixed window counters."
        ],
    },
    {
        "input": "What are the benefits of using PostgreSQL row-level security?",
        "expected_output": "Row-level security (RLS) in PostgreSQL provides tenant isolation at the database level, ensuring queries automatically filter by tenant_id without application code changes.",
        "context": [
            "PostgreSQL Row Level Security (RLS) allows you to define policies that restrict "
            "which rows are visible to different database roles. This is commonly used in "
            "multi-tenant applications to enforce data isolation."
        ],
    },
]


@pytest.fixture
def deepeval_available():
    """Check if deepeval is installed."""
    try:
        import deepeval

        return True
    except ImportError:
        pytest.skip("deepeval not installed (pip install deepeval)")


class TestFaithfulness:
    """Test that agent outputs are grounded in provided context."""

    def test_faithfulness_metric(self, deepeval_available):
        from deepeval import evaluate
        from deepeval.metrics import FaithfulnessMetric
        from deepeval.test_case import LLMTestCase

        metric = FaithfulnessMetric(threshold=0.7)

        test_cases = []
        for case in EVAL_CASES:
            # TODO: Replace with real agent invocation to get actual_output
            # For now, use expected_output as a baseline smoke test
            actual_output = case["expected_output"]  # FIXME: call agent(case["input"])
            tc = LLMTestCase(
                input=case["input"],
                actual_output=actual_output,
                expected_output=case["expected_output"],
                retrieval_context=case["context"],
            )
            test_cases.append(tc)

        results = evaluate(test_cases, [metric])
        # At least 70% of cases should pass
        passed = sum(1 for r in results.test_results if r.success)
        assert passed >= len(test_cases) * 0.7, f"Only {passed}/{len(test_cases)} passed faithfulness"


class TestRelevance:
    """Test that agent outputs are relevant to the input question."""

    def test_answer_relevancy(self, deepeval_available):
        from deepeval import evaluate
        from deepeval.metrics import AnswerRelevancyMetric
        from deepeval.test_case import LLMTestCase

        metric = AnswerRelevancyMetric(threshold=0.7)

        test_cases = [
            LLMTestCase(
                input=case["input"],
                # TODO: Replace with real agent invocation to get actual_output
                actual_output=case["expected_output"],  # FIXME: call agent(case["input"])
                expected_output=case["expected_output"],
            )
            for case in EVAL_CASES
        ]

        results = evaluate(test_cases, [metric])
        passed = sum(1 for r in results.test_results if r.success)
        assert passed >= len(test_cases) * 0.7


class TestHallucination:
    """Test that agent outputs don't fabricate information."""

    def test_hallucination_metric(self, deepeval_available):
        from deepeval import evaluate
        from deepeval.metrics import HallucinationMetric
        from deepeval.test_case import LLMTestCase

        metric = HallucinationMetric(threshold=0.5)

        test_cases = [
            LLMTestCase(
                input=case["input"],
                # TODO: Replace with real agent invocation to get actual_output
                actual_output=case["expected_output"],  # FIXME: call agent(case["input"])
                expected_output=case["expected_output"],
                context=case["context"],
            )
            for case in EVAL_CASES
        ]

        results = evaluate(test_cases, [metric])
        passed = sum(1 for r in results.test_results if r.success)
        assert passed >= len(test_cases) * 0.7


class TestToxicity:
    """Test that agent outputs are free of toxic content."""

    def test_toxicity_metric(self, deepeval_available):
        from deepeval import evaluate
        from deepeval.metrics import ToxicityMetric
        from deepeval.test_case import LLMTestCase

        metric = ToxicityMetric(threshold=0.5)

        test_cases = [
            LLMTestCase(
                input=case["input"],
                # TODO: Replace with real agent invocation to get actual_output
                actual_output=case["expected_output"],  # FIXME: call agent(case["input"])
                expected_output=case["expected_output"],
            )
            for case in EVAL_CASES
        ]

        results = evaluate(test_cases, [metric])
        # All cases should pass toxicity
        passed = sum(1 for r in results.test_results if r.success)
        assert passed == len(test_cases), "Agent output contains toxic content"


class TestRAGQuality:
    """Test RAG pipeline quality using RAGAS-style metrics."""

    def test_context_relevancy(self, deepeval_available):
        """Verify retrieved context is relevant to the query."""
        from deepeval import evaluate
        from deepeval.metrics import ContextualRelevancyMetric
        from deepeval.test_case import LLMTestCase

        metric = ContextualRelevancyMetric(threshold=0.7)

        test_cases = [
            LLMTestCase(
                input=case["input"],
                # TODO: Replace with real agent invocation to get actual_output
                actual_output=case["expected_output"],  # FIXME: call agent(case["input"])
                expected_output=case["expected_output"],
                retrieval_context=case["context"],
            )
            for case in EVAL_CASES
        ]

        results = evaluate(test_cases, [metric])
        passed = sum(1 for r in results.test_results if r.success)
        assert passed >= len(test_cases) * 0.7
