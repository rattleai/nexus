"""PDF document parser using pdfplumber (primary) with pymupdf fallback."""

from __future__ import annotations

import io
import time
from typing import Any

import structlog

from app.docprocessor.base import ExtractedSection, ExtractedTable, ExtractionResult

logger = structlog.stdlib.get_logger()


class PDFParser:
    """Extract text and tables from PDF files using pdfplumber (primary) with pymupdf fallback."""

    MAX_PAGES = 500
    MAX_FILE_SIZE = 100_000_000  # 100 MB

    async def parse(
        self,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str = "",
    ) -> ExtractionResult:
        """Parse PDF and extract structured content."""
        start = time.monotonic()
        result = ExtractionResult(source_type="pdf", source_name=filename or file_path or "unknown.pdf")

        if file_bytes and len(file_bytes) > self.MAX_FILE_SIZE:
            result.metadata["error"] = f"File too large ({len(file_bytes)} bytes, max {self.MAX_FILE_SIZE})"
            result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
            return result

        try:
            sections, tables, raw_text, metadata = self._extract_with_pdfplumber(file_path, file_bytes)
            result.sections = sections
            result.tables = tables
            result.raw_text = raw_text
            result.metadata = metadata
        except Exception as exc:
            logger.warning("pdfplumber_extraction_failed", error=str(exc), filename=filename)
            try:
                sections, raw_text, metadata = self._extract_with_pymupdf(file_path, file_bytes)
                result.sections = sections
                result.raw_text = raw_text
                result.metadata = metadata
            except Exception as fallback_exc:
                logger.error(
                    "pdf_extraction_failed",
                    error=str(fallback_exc),
                    filename=filename,
                )

        result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
        return result

    def _extract_with_pdfplumber(
        self,
        file_path: str | None,
        file_bytes: bytes | None,
    ) -> tuple[list[ExtractedSection], list[ExtractedTable], str, dict[str, Any]]:
        """Extract content using pdfplumber (best for tables)."""
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError("pdfplumber is not installed. Install with: pip install pdfplumber") from exc

        sections: list[ExtractedSection] = []
        tables: list[ExtractedTable] = []
        all_text_parts: list[str] = []
        metadata: dict[str, Any] = {}

        open_arg: Any = file_path if file_path else io.BytesIO(file_bytes)  # type: ignore[arg-type]
        with pdfplumber.open(open_arg) as pdf:
            metadata["page_count"] = len(pdf.pages)
            if pdf.metadata:
                for key in ("Title", "Author", "Subject", "Creator"):
                    if pdf.metadata.get(key):
                        metadata[key.lower()] = pdf.metadata[key]

            for page_num, page in enumerate(pdf.pages[: self.MAX_PAGES], start=1):
                # Extract tables from this page
                page_tables = self._extract_page_tables(page, page_num)
                tables.extend(page_tables)

                # Extract text
                page_text = page.extract_text() or ""
                if page_text.strip():
                    all_text_parts.append(page_text)
                    sections.append(
                        ExtractedSection(
                            title=f"Page {page_num}",
                            content=page_text.strip(),
                            level=1,
                            tables=page_tables,
                        )
                    )

        raw_text = "\n\n".join(all_text_parts)
        return sections, tables, raw_text, metadata

    def _extract_page_tables(self, page: Any, page_num: int) -> list[ExtractedTable]:
        """Extract tables from a single pdfplumber page."""
        extracted: list[ExtractedTable] = []
        try:
            raw_tables = page.extract_tables()
        except Exception:
            return extracted

        for raw_table in raw_tables or []:
            if not raw_table or len(raw_table) < 2:
                continue

            # First row as headers, rest as data
            headers = [str(cell or "").strip() for cell in raw_table[0]]
            rows = [[str(cell or "").strip() for cell in row] for row in raw_table[1:] if any(cell for cell in row)]

            if headers or rows:
                extracted.append(
                    ExtractedTable(
                        headers=headers,
                        rows=rows,
                        source_page=page_num,
                    )
                )
        return extracted

    def _extract_with_pymupdf(
        self,
        file_path: str | None,
        file_bytes: bytes | None,
    ) -> tuple[list[ExtractedSection], str, dict[str, Any]]:
        """Fallback extraction using PyMuPDF (fitz) for text only."""
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PyMuPDF is not installed. Install with: pip install pymupdf") from exc

        sections: list[ExtractedSection] = []
        all_text_parts: list[str] = []
        metadata: dict[str, Any] = {}

        doc = fitz.open(file_path) if file_path else fitz.open(stream=file_bytes, filetype="pdf")

        try:
            metadata["page_count"] = len(doc)
            doc_metadata = doc.metadata or {}
            for key in ("title", "author", "subject", "creator"):
                if doc_metadata.get(key):
                    metadata[key] = doc_metadata[key]

            for page_num in range(min(len(doc), self.MAX_PAGES)):
                page = doc[page_num]
                page_text = page.get_text()
                if page_text.strip():
                    all_text_parts.append(page_text)
                    sections.append(
                        ExtractedSection(
                            title=f"Page {page_num + 1}",
                            content=page_text.strip(),
                            level=1,
                        )
                    )
        finally:
            doc.close()

        raw_text = "\n\n".join(all_text_parts)
        return sections, raw_text, metadata
