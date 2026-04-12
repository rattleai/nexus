"""LLM-as-judge for RAG quality evaluation.

Uses a cheap LLM (Claude Haiku) to evaluate:
- Faithfulness: Is the answer grounded in the retrieved context?
- Answer Relevancy: Does the answer address the query?

Scores are normalized to [0, 1].
"""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


_FAITHFULNESS_PROMPT = """You are evaluating whether an AI assistant's answer is faithful to the provided context.

Context (retrieved documents):
{context}

Question: {query}

Answer: {answer}

Rate the faithfulness of the answer on a scale of 0 to 10, where:
- 0: The answer contains information not found in the context (hallucination)
- 5: The answer partially uses the context but adds unsupported claims
- 10: The answer is entirely grounded in and supported by the context

Respond with ONLY a single number (0-10). No explanation."""

_RELEVANCY_PROMPT = """You are evaluating whether an AI assistant's answer is relevant to the question.

Question: {query}

Answer: {answer}

Rate the relevancy of the answer on a scale of 0 to 10, where:
- 0: The answer does not address the question at all
- 5: The answer partially addresses the question
- 10: The answer directly and completely addresses the question

Respond with ONLY a single number (0-10). No explanation."""


class LLMJudge:
    """Evaluate RAG quality using LLM-as-judge."""

    async def evaluate_faithfulness(
        self,
        query: str,
        context_chunks: list[str],
        generated_answer: str,
    ) -> float:
        """Score how well the answer stays grounded in the context.

        Returns a score in [0.0, 1.0].
        """
        context = "\n\n---\n\n".join(context_chunks[:10])  # Cap context
        prompt = _FAITHFULNESS_PROMPT.format(
            context=context, query=query, answer=generated_answer,
        )
        return await self._score(prompt)

    async def evaluate_answer_relevancy(
        self,
        query: str,
        generated_answer: str,
    ) -> float:
        """Score how relevant the answer is to the query.

        Returns a score in [0.0, 1.0].
        """
        prompt = _RELEVANCY_PROMPT.format(query=query, answer=generated_answer)
        return await self._score(prompt)

    async def _score(self, prompt: str) -> float:
        """Call the judge LLM and parse the score."""
        try:
            from app.ai.gateway import ai_gateway

            response = await ai_gateway.complete(
                model=settings.RAG_CONTEXTUAL_MODEL,  # Cheap model
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0,
            )

            content = ""
            if response and hasattr(response, "content"):
                content = response.content
            elif isinstance(response, dict):
                content = response.get("content", "")

            # Parse the numeric score
            score_str = content.strip().split()[0] if content.strip() else "0"
            score = float(score_str)
            return max(0.0, min(1.0, score / 10.0))  # Normalize to [0, 1]

        except Exception:
            logger.warning("llm_judge_failed", exc_info=True)
            return 0.0


# Module-level singleton
llm_judge = LLMJudge()
