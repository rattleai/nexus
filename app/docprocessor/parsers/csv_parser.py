"""CSV file parser."""

from __future__ import annotations

import csv
import io
import time

import structlog

from app.docprocessor.base import ExtractionResult, ExtractedSection, ExtractedTable

logger = structlog.stdlib.get_logger()


class CSVParser:
    """Extract structured data from CSV files."""

    async def parse(
        self,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str = "",
    ) -> ExtractionResult:
        """Parse CSV file and extract structured content."""
        start = time.monotonic()
        result = ExtractionResult(source_type="csv", source_name=filename or file_path or "unknown.csv")

        try:
            if file_path:
                with open(file_path, newline="", encoding="utf-8", errors="replace") as f:
                    text_content = f.read()
            else:
                text_content = (file_bytes or b"").decode("utf-8", errors="replace")

            if not text_content.strip():
                result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
                return result

            # Detect delimiter using csv.Sniffer
            try:
                sample = text_content[:8192]
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel  # type: ignore[assignment]

            reader = csv.reader(io.StringIO(text_content), dialect)
            rows_data: list[list[str]] = []
            _FORMULA_CHARS = frozenset("=+-@")
            for row in reader:
                stripped = []
                for cell in row:
                    cell = cell.strip()
                    # Sanitize formula-injection characters
                    if cell and cell[0] in _FORMULA_CHARS:
                        cell = f"'{cell}"
                    stripped.append(cell)
                if any(v for v in stripped):
                    rows_data.append(stripped)

            if not rows_data:
                result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
                return result

            # First row as headers
            headers = rows_data[0]
            data_rows = rows_data[1:]

            table = ExtractedTable(headers=headers, rows=data_rows)
            result.tables.append(table)

            # Build text representation
            text_lines = [" | ".join(headers), "-" * 40]
            for row in data_rows[:100]:
                text_lines.append(" | ".join(row))
            if len(data_rows) > 100:
                text_lines.append(f"... and {len(data_rows) - 100} more rows")

            text_repr = "\n".join(text_lines)
            result.raw_text = text_repr
            result.sections.append(
                ExtractedSection(
                    title=filename or "CSV Data",
                    content=text_repr,
                    level=1,
                    tables=[table],
                )
            )

            result.metadata["row_count"] = len(data_rows)
            result.metadata["column_count"] = len(headers)

        except Exception as exc:
            logger.error("csv_extraction_failed", error=str(exc), filename=filename)
            result.metadata["error"] = str(exc)

        result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
        return result
