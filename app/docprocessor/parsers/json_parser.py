"""JSON/JSONL document parser."""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

from app.docprocessor.base import ExtractedSection, ExtractedTable, ExtractionResult

logger = structlog.stdlib.get_logger()


class JSONParser:
    """Extract structured data from JSON/JSONL files."""

    async def parse(
        self,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str = "",
    ) -> ExtractionResult:
        """Parse JSON or JSONL file and extract structured content."""
        start = time.monotonic()
        result = ExtractionResult(source_type="json", source_name=filename or file_path or "unknown.json")

        try:
            if file_bytes:
                text_content = file_bytes.decode("utf-8", errors="replace")
            elif file_path:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    text_content = f.read()
            else:
                result.metadata["error"] = "No file path or bytes provided"
                result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
                return result

            if not text_content.strip():
                result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
                return result

            is_jsonl = filename.endswith(".jsonl") or filename.endswith(".ndjson")

            if is_jsonl:
                data = self._parse_jsonl(text_content)
            else:
                data = json.loads(text_content)

            if isinstance(data, list):
                # Array of objects -> table
                table = self._array_to_table(data)
                if table:
                    result.tables.append(table)
                    result.sections.append(
                        ExtractedSection(
                            title=filename or "JSON Array",
                            content=self._table_to_text(table),
                            level=1,
                            tables=[table],
                        )
                    )
                result.metadata["item_count"] = len(data)
            elif isinstance(data, dict):
                # Single object -> flatten and represent
                flat = self._flatten_dict(data)
                headers = list(flat.keys())
                rows = [list(flat.values())]
                table = ExtractedTable(headers=headers, rows=[[str(v) for v in rows[0]]])
                result.tables.append(table)

                text_lines = [f"{k}: {v}" for k, v in flat.items()]
                section_text = "\n".join(text_lines)
                result.sections.append(
                    ExtractedSection(
                        title=filename or "JSON Object",
                        content=section_text,
                        level=1,
                        tables=[table],
                    )
                )
                result.metadata["key_count"] = len(flat)

            result.raw_text = text_content[:50000]  # Cap raw text

        except json.JSONDecodeError as exc:
            logger.error("json_parse_error", error=str(exc), filename=filename)
            result.metadata["error"] = f"Invalid JSON: {exc}"
        except Exception as exc:
            logger.error("json_extraction_failed", error=str(exc), filename=filename)
            result.metadata["error"] = str(exc)

        result.extraction_duration_ms = int((time.monotonic() - start) * 1000)
        return result

    @staticmethod
    def _parse_jsonl(text: str) -> list[Any]:
        """Parse JSONL (newline-delimited JSON) into a list of objects."""
        objects: list[Any] = []
        for line in text.strip().splitlines():
            line = line.strip()
            if line:
                try:
                    objects.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return objects

    def _array_to_table(self, data: list[Any]) -> ExtractedTable | None:
        """Convert an array of objects to an ExtractedTable."""
        if not data:
            return None

        # Collect all keys from all objects (for heterogeneous arrays)
        all_keys: list[str] = []
        seen: set[str] = set()
        for item in data:
            if isinstance(item, dict):
                flat = self._flatten_dict(item)
                for k in flat:
                    if k not in seen:
                        all_keys.append(k)
                        seen.add(k)

        if not all_keys:
            return None

        rows: list[list[str]] = []
        for item in data:
            if isinstance(item, dict):
                flat = self._flatten_dict(item)
                row = [str(flat.get(k, "")) for k in all_keys]
            else:
                row = [str(item)] + [""] * (len(all_keys) - 1)
            rows.append(row)

        return ExtractedTable(headers=all_keys, rows=rows)

    @staticmethod
    def _flatten_dict(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        """Flatten a nested dict using dot-notation keys."""
        items: dict[str, Any] = {}
        for k, v in d.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                items.update(JSONParser._flatten_dict(v, new_key))
            elif isinstance(v, list):
                # Represent lists as JSON strings for table cells
                items[new_key] = json.dumps(v, default=str)
            else:
                items[new_key] = v
        return items

    @staticmethod
    def _table_to_text(table: ExtractedTable) -> str:
        """Convert table to a text representation."""
        lines = ["\t".join(table.headers)]
        for row in table.rows[:100]:  # Cap at 100 rows
            lines.append("\t".join(row))
        return "\n".join(lines)
