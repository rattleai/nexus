"""Format-specific document parsers."""

from __future__ import annotations

from app.docprocessor.parsers.csv_parser import CSVParser
from app.docprocessor.parsers.excel_parser import ExcelParser
from app.docprocessor.parsers.json_parser import JSONParser
from app.docprocessor.parsers.pdf_parser import PDFParser
from app.docprocessor.parsers.web_parser import WebParser
from app.docprocessor.parsers.word_parser import WordParser

__all__ = [
    "CSVParser",
    "ExcelParser",
    "JSONParser",
    "PDFParser",
    "WebParser",
    "WordParser",
]
