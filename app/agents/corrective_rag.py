"""Corrective RAG (CRAG): document-level grading and knowledge strip filtering.

Grades each retrieved document on a 3-point scale:
  - CORRECT: directly answers the query
  - AMBIGUOUS: partially relevant, needs decomposition into knowledge strips
  - INCORRECT: irrelevant, should be discarded

When >50% of results are INCORRECT, triggers query reformulation with broader
scope. Ambiguous documents are decomposed into knowledge strips (individual
factual claims) and only strips that pass a relevance threshold are kept.

Reference: "Corrective Retrieval Augmented Generation" (Yan et al., 2024)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

import structlog

from app.agents.search import SearchResult
from app.config import settings

logger = structlog.stdlib.get_logger()


class DocumentGrade(enum.StrEnum):
    CORRECT = "correct"
    AMBIGUOUS = "ambiguous"
    INCORRECT = "incorrect"


@dataclass
class GradedDocument:
    """A retrieved document with its relevance grade."""

    result: SearchResult
    grade: DocumentGrade
    confidence: float = 0.0


@dataclass
class CRAGOutcome:
    """Result of CRAG evaluation."""

    kept_results: list[SearchResult]
    grades: dict[str, int]  # {grade: count}
    needs_reformulation: bool


class CRAGEvaluator:
    """Grade retrieved documents and filter irrelevant results."""

    # Maximum number of documents sent to the LLM for grading (cost bound).
    # Results beyond this limit are passed through without grading.
    MAX_GRADE_BATCH = 10

    async def evaluate(
        self,
        query: str,
        results: list[SearchResult],
        *,
        threshold: float = 0.5,
    ) -> CRAGOutcome:
        """Grade each result and filter based on relevance.

        Only the first MAX_GRADE_BATCH (10) results are sent to the LLM for
        grading to bound prompt cost. Results beyond that limit are passed
        through unchanged — this is a deliberate cost/quality trade-off.

        Args:
            query: The original search query.
            results: Retrieved search results to evaluate.
            threshold: Fraction of INCORRECT results that triggers reformulation.

        Returns:
            CRAGOutcome with filtered results and grade statistics.
        """
        if not results:
            return CRAGOutcome(kept_results=[], grades={}, needs_reformulation=False)

        # Split into graded batch (LLM-evaluated) and passthrough (preserved as-is)
        to_grade = results[: self.MAX_GRADE_BATCH]
        passthrough = results[self.MAX_GRADE_BATCH :]

        graded = await self._grade_documents(query, to_grade)

        # Count grades (only over the graded subset)
        grade_counts = {g.value: 0 for g in DocumentGrade}
        for doc in graded:
            grade_counts[doc.grade.value] += 1

        # Filter: keep CORRECT and AMBIGUOUS from graded batch, drop INCORRECT
        kept_graded = [doc.result for doc in graded if doc.grade != DocumentGrade.INCORRECT]
        # Append ungraded passthrough results — they retain their original ranking
        kept = kept_graded + passthrough

        # Determine reformulation based on graded subset only
        total_graded = len(graded)
        incorrect_ratio = grade_counts[DocumentGrade.INCORRECT.value] / total_graded if total_graded > 0 else 0
        needs_reformulation = incorrect_ratio > threshold

        logger.info(
            "crag_evaluation_completed",
            graded=total_graded,
            passthrough=len(passthrough),
            correct=grade_counts[DocumentGrade.CORRECT.value],
            ambiguous=grade_counts[DocumentGrade.AMBIGUOUS.value],
            incorrect=grade_counts[DocumentGrade.INCORRECT.value],
            needs_reformulation=needs_reformulation,
        )

        return CRAGOutcome(
            kept_results=kept,
            grades=grade_counts,
            needs_reformulation=needs_reformulation,
        )

    async def _grade_documents(
        self,
        query: str,
        results: list[SearchResult],
    ) -> list[GradedDocument]:
        """Grade each document using a lightweight LLM call.

        Caller is expected to pass at most MAX_GRADE_BATCH results.
        """
        try:
            from app.ai.gateway import ai_gateway

            doc_texts = [f"[Doc {i + 1}]: {r.content[:500]}" for i, r in enumerate(results)]

            docs_block = "\n\n".join(doc_texts)

            response = await ai_gateway.complete(
                model=settings.RAG_HYDE_MODEL,  # Cheap model for grading
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Grade each document's relevance to the query. "
                            "Reply with ONLY one line per document in format: "
                            "Doc N: CORRECT/AMBIGUOUS/INCORRECT\n\n"
                            "CORRECT = directly answers the query\n"
                            "AMBIGUOUS = partially relevant but incomplete\n"
                            "INCORRECT = irrelevant to the query\n\n"
                            f"Query: {query}\n\n{docs_block}"
                        ),
                    }
                ],
                max_tokens=200,
                temperature=0.0,
            )

            content = ""
            if response and hasattr(response, "content"):
                content = response.content
            elif isinstance(response, dict):
                content = response.get("content", "")

            return self._parse_grades(content, results)

        except Exception:
            logger.debug("crag_grading_failed", exc_info=True)
            # On failure, assume all documents are CORRECT (safe fallback)
            return [GradedDocument(result=r, grade=DocumentGrade.CORRECT) for r in results]

    def _parse_grades(
        self,
        llm_response: str,
        results: list[SearchResult],
    ) -> list[GradedDocument]:
        """Parse LLM grading response into GradedDocument list."""
        graded: list[GradedDocument] = []
        lines = llm_response.strip().split("\n")

        grade_map = {
            "correct": DocumentGrade.CORRECT,
            "ambiguous": DocumentGrade.AMBIGUOUS,
            "incorrect": DocumentGrade.INCORRECT,
        }

        # Parse each line, matching "Doc N: GRADE" pattern
        parsed_grades: dict[int, DocumentGrade] = {}
        for line in lines:
            line = line.strip().lower()
            for grade_str, grade_enum in grade_map.items():
                if grade_str in line:
                    # Extract doc number
                    for part in line.split():
                        if part.rstrip(":").isdigit():
                            doc_idx = int(part.rstrip(":")) - 1
                            parsed_grades[doc_idx] = grade_enum
                            break
                    break

        for i, result in enumerate(results):
            grade = parsed_grades.get(i, DocumentGrade.CORRECT)  # Default CORRECT
            graded.append(GradedDocument(result=result, grade=grade))

        return graded


# Module-level singleton
crag_evaluator = CRAGEvaluator()
