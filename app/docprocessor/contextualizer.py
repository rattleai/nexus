"""Contextual retrieval: prepend document context to chunks before embedding.

Implements Anthropic's contextual retrieval approach: each chunk gets a
short preamble containing the document title, section, and a brief
summary. This makes chunks self-contained, improving retrieval quality
by up to 49% when combined with hybrid search.

The summary is generated once per document using a cheap LLM call (Haiku),
then per-chunk preambles are constructed from the summary + section metadata.
"""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()

# Maximum summary length to keep costs and latency low
_MAX_SUMMARY_TOKENS = 150


class ChunkContextualizer:
    """Generate contextual preambles for document chunks."""

    async def contextualize(
        self,
        chunks: list[tuple[str, dict]],
        *,
        document_name: str = "",
        document_text: str = "",
    ) -> list[tuple[str, str, dict]]:
        """Add context preamble to each chunk.

        Args:
            chunks: List of (chunk_text, metadata) tuples.
            document_name: Name/title of the source document.
            document_text: Full document text for summary generation.

        Returns:
            List of (preamble, content_with_context, metadata) tuples.
        """
        if not chunks:
            return []

        # Generate document summary (one LLM call per document, not per chunk)
        summary = await self._generate_summary(document_name, document_text)

        results = []
        for chunk_text, metadata in chunks:
            section = metadata.get("section_title", "")
            preamble = self._build_preamble(document_name, section, summary)
            content_with_context = f"{preamble}\n\n{chunk_text}" if preamble else chunk_text
            results.append((preamble, content_with_context, metadata))

        logger.info(
            "chunks_contextualized",
            chunk_count=len(results),
            document_name=document_name[:100],
        )
        return results

    async def _generate_summary(self, document_name: str, document_text: str) -> str:
        """Generate a brief document summary via cheap LLM call."""
        if not document_text:
            return ""

        try:
            from app.ai.gateway import ai_gateway

            # Use a truncated version of the document for the summary prompt
            truncated = document_text[:4000]

            response = await ai_gateway.complete(
                model=settings.RAG_CONTEXTUAL_MODEL,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Summarize this document in 1-2 sentences. "
                        f"Focus on the main topic and purpose.\n\n"
                        f"Document: {document_name}\n\n{truncated}"
                    ),
                }],
                max_tokens=_MAX_SUMMARY_TOKENS,
                temperature=0.0,
            )

            summary = ""
            if response and hasattr(response, "content"):
                summary = response.content
            elif isinstance(response, dict):
                summary = response.get("content", "")

            return summary.strip()[:500]

        except Exception:
            logger.warning("contextual_summary_failed", exc_info=True)
            return ""

    @staticmethod
    def _build_preamble(document_name: str, section_title: str, summary: str) -> str:
        """Build the context preamble from available metadata."""
        parts = []

        if document_name:
            parts.append(f"From document: {document_name}")
        if section_title:
            parts.append(f"Section: {section_title}")
        if summary:
            parts.append(f"Document context: {summary}")

        return ". ".join(parts) + "." if parts else ""


# Module-level singleton
chunk_contextualizer = ChunkContextualizer()
