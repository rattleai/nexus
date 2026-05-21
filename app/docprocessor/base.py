"""Common Intermediate Representation (CIR) dataclasses for document extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedTable:
    """A table extracted from a document."""

    headers: list[str]
    rows: list[list[str]]
    source_page: int | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "headers": self.headers,
            "rows": self.rows,
            "source_page": self.source_page,
            "confidence": self.confidence,
        }


@dataclass
class ExtractedSection:
    """A section of text extracted from a document, optionally containing tables."""

    title: str
    content: str
    level: int = 1
    tables: list[ExtractedTable] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "level": self.level,
            "tables": [t.to_dict() for t in self.tables],
        }


@dataclass
class ExtractionResult:
    """Result of extracting structured content from a document or URL."""

    source_type: str  # "pdf", "excel", "word", "csv", "json", "url"
    source_name: str
    sections: list[ExtractedSection] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    extraction_duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_name": self.source_name,
            "sections": [s.to_dict() for s in self.sections],
            "tables": [t.to_dict() for t in self.tables],
            "raw_text": self.raw_text,
            "metadata": self.metadata,
            "extraction_duration_ms": self.extraction_duration_ms,
        }

    @property
    def has_tables(self) -> bool:
        return self.table_count > 0

    @property
    def table_count(self) -> int:
        section_tables = sum(len(s.tables) for s in self.sections)
        return len(self.tables) + section_tables

    @property
    def section_count(self) -> int:
        return len(self.sections)
