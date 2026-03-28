"""Document processing pipeline for extracting structured content from files and URLs."""

from __future__ import annotations

from app.docprocessor.base import ExtractionResult, ExtractedSection, ExtractedTable
from app.docprocessor.indexer import ContentIndexer
from app.docprocessor.processor import DocumentProcessor

__all__ = [
    "DocumentProcessor",
    "ContentIndexer",
    "ExtractionResult",
    "ExtractedSection",
    "ExtractedTable",
]
