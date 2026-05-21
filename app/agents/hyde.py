"""HyDE: Hypothetical Document Embeddings for improved retrieval.

When a user asks "What is our warranty policy?", the query embedding
is far from the actual policy document in vector space. HyDE generates
a hypothetical answer document, embeds that instead, and searches with
the hypothetical embedding — dramatically improving recall for
question-type queries.

Only activated for question-type queries (detected by QueryRouter).
"""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


class HyDEGenerator:
    """Generate hypothetical document embeddings for improved retrieval."""

    async def generate_hypothetical(self, query: str) -> str | None:
        """Generate a hypothetical answer document for the given query.

        Returns the hypothetical document text, or None if generation fails.
        The caller should embed this text and use it for vector search.
        """
        if not settings.RAG_HYDE_ENABLED:
            return None

        try:
            from app.ai.gateway import ai_gateway

            response = await ai_gateway.complete(
                model=settings.RAG_HYDE_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Write a short, factual document passage that would "
                            "directly answer this question. Write as if you are "
                            "writing the actual source document, not an answer. "
                            "Keep it under 200 words.\n\n"
                            f"Question: {query}"
                        ),
                    }
                ],
                max_tokens=300,
                temperature=0.0,
            )

            content = ""
            if response and hasattr(response, "content"):
                content = response.content
            elif isinstance(response, dict):
                content = response.get("content", "")

            hypothetical = content.strip()
            if not hypothetical:
                return None

            logger.info(
                "hyde_generated",
                query=query[:100],
                hypothetical_len=len(hypothetical),
            )
            return hypothetical

        except Exception:
            logger.warning("hyde_generation_failed", exc_info=True)
            return None


# Module-level singleton
hyde_generator = HyDEGenerator()
