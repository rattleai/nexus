"""Unified document processor that dispatches to format-specific parsers."""

from __future__ import annotations

import asyncio
import mimetypes
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from app.docprocessor.base import ExtractionResult
from app.docprocessor.parsers.csv_parser import CSVParser
from app.docprocessor.parsers.excel_parser import ExcelParser
from app.docprocessor.parsers.json_parser import JSONParser
from app.docprocessor.parsers.pdf_parser import PDFParser
from app.docprocessor.parsers.web_parser import WebParser
from app.docprocessor.parsers.word_parser import WordParser

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models.datasource import DataSource

logger = structlog.stdlib.get_logger()


class DocumentProcessor:
    """Unified document processor that dispatches to format-specific parsers."""

    MIME_MAP: dict[str, type] = {
        "application/pdf": PDFParser,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ExcelParser,
        "application/vnd.ms-excel": ExcelParser,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": WordParser,
        "text/csv": CSVParser,
        "application/json": JSONParser,
        "text/html": WebParser,
    }

    # Extension fallbacks for when MIME detection fails
    _EXT_MAP: dict[str, type] = {
        ".pdf": PDFParser,
        ".xlsx": ExcelParser,
        ".xls": ExcelParser,
        ".docx": WordParser,
        ".csv": CSVParser,
        ".json": JSONParser,
        ".jsonl": JSONParser,
        ".ndjson": JSONParser,
        ".html": WebParser,
        ".htm": WebParser,
    }

    def __init__(self) -> None:
        self._parser_cache: dict[type, Any] = {}

    def _get_parser(self, parser_cls: type) -> Any:
        """Get or create a parser instance (cached per class)."""
        if parser_cls not in self._parser_cache:
            self._parser_cache[parser_cls] = parser_cls()
        return self._parser_cache[parser_cls]

    def _resolve_parser(self, mime_type: str, filename: str = "") -> Any | None:
        """Resolve the correct parser for a given MIME type or filename."""
        # Try MIME type first
        parser_cls = self.MIME_MAP.get(mime_type)
        if parser_cls:
            return self._get_parser(parser_cls)

        # Fall back to extension
        if filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            parser_cls = self._EXT_MAP.get(ext)
            if parser_cls:
                return self._get_parser(parser_cls)

        return None

    async def process(self, file_key: str, tenant_id: UUID) -> ExtractionResult:
        """Download from S3 and extract content.

        Args:
            file_key: S3 object key for the file.
            tenant_id: Tenant owning the file.

        Returns:
            ExtractionResult with extracted content.
        """
        from app.storage.s3 import S3Storage

        start = time.monotonic()
        storage = S3Storage()

        try:
            file_bytes = await storage.async_download(file_key)
        except Exception as exc:
            logger.error("document_download_failed", file_key=file_key, error=str(exc))
            return ExtractionResult(
                source_type="unknown",
                source_name=file_key,
                metadata={"error": f"Download failed: {exc}"},
                extraction_duration_ms=int((time.monotonic() - start) * 1000),
            )

        # Detect MIME type from the key/filename
        filename = file_key.rsplit("/", 1)[-1] if "/" in file_key else file_key
        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"

        result = await self.process_bytes(file_bytes, filename, mime_type)
        result.metadata["file_key"] = file_key
        result.metadata["tenant_id"] = str(tenant_id)
        return result

    async def process_url(self, url: str, tenant_id: UUID) -> ExtractionResult:
        """Fetch and extract content from a URL.

        Args:
            url: The web URL to fetch.
            tenant_id: Tenant requesting the extraction.

        Returns:
            ExtractionResult with extracted content.
        """
        parser = self._get_parser(WebParser)
        result = await parser.parse_url(url)
        result.metadata["tenant_id"] = str(tenant_id)
        return result

    async def process_bytes(self, data: bytes, filename: str, mime_type: str) -> ExtractionResult:
        """Process raw bytes with a known MIME type.

        Args:
            data: Raw file bytes.
            filename: Original filename (used for extension fallback and naming).
            mime_type: MIME type of the data.

        Returns:
            ExtractionResult with extracted content.
        """
        # Cross-check MIME type with magic bytes when possible
        mime_type = self._validate_mime(data, filename, mime_type)

        parser = self._resolve_parser(mime_type, filename)
        if parser is None:
            logger.warning("unsupported_document_type", mime_type=mime_type, filename=filename)
            return ExtractionResult(
                source_type="unknown",
                source_name=filename,
                raw_text=data.decode("utf-8", errors="replace")[:50000] if len(data) < 10_000_000 else "",
                metadata={"error": f"Unsupported MIME type: {mime_type}", "mime_type": mime_type},
            )

        # WebParser uses parse_url, not parse -- shouldn't reach here for HTML bytes normally
        # but handle gracefully if it does
        if isinstance(parser, WebParser):
            return ExtractionResult(
                source_type="url",
                source_name=filename,
                raw_text=data.decode("utf-8", errors="replace")[:50000],
                metadata={"note": "HTML bytes processed as raw text; use process_url for full extraction"},
            )

        return await parser.parse(file_bytes=data, filename=filename)

    async def process_data_source(
        self,
        ds: "DataSource",
        db: "AsyncSession",
    ) -> ExtractionResult:
        """Dispatch extraction based on ``ds.source_type``.

        This is the canonical entry point for the Celery extraction task.
        Concrete fetch logic lives in the type-specific branches:

        * ``UPLOAD`` — fetch from S3 by ``file_key``.
        * ``URL`` — fetch and parse the web page.
        * ``CLOUD_DRIVE`` — download via the provider-specific ``DriveAdapter``
          (Dropbox / Google Drive / OneDrive), then hand off to
          ``process_bytes`` so the same parser/chunker/embedder path applies
          as for local uploads.
        * ``PASTE`` — no-op; paste content is already materialized as the
          first chunk at create time.

        Enriches ``ds.filename`` / ``ds.mime_type`` / ``ds.file_size`` for
        cloud-drive sources so the UI and downstream audit show real metadata.
        """
        from app.db.models.datasource import DataSourceType

        if ds.source_type == DataSourceType.UPLOAD:
            if not ds.file_key:
                raise ValueError(
                    f"UPLOAD DataSource {ds.id} has no file_key"
                )
            return await self.process(ds.file_key, ds.tenant_id)

        if ds.source_type == DataSourceType.URL:
            if not ds.url:
                raise ValueError(f"URL DataSource {ds.id} has no url")
            return await self.process_url(ds.url, ds.tenant_id)

        if ds.source_type == DataSourceType.CLOUD_DRIVE:
            return await self._process_cloud_drive(ds, db)

        if ds.source_type == DataSourceType.PASTE:
            return ExtractionResult(
                source_type="paste",
                source_name=ds.name,
                raw_text="",
                metadata={
                    "note": "paste content materialized at create time; "
                    "extraction task is a no-op",
                },
            )

        raise ValueError(
            f"Unsupported DataSource.source_type: {ds.source_type}"
        )

    async def _process_cloud_drive(
        self,
        ds: "DataSource",
        db: "AsyncSession",
    ) -> ExtractionResult:
        """Fetch a cloud-drive file via the connector system, then extract."""
        from sqlalchemy import select as sa_select

        from app.connectors.drive import resolve_adapter
        from app.connectors.models import ConnectorDefinition, TenantConnection

        if not ds.connection_id or not ds.connector_slug or not ds.cloud_file_id:
            raise ValueError(
                f"CLOUD_DRIVE DataSource {ds.id} missing connection_id, "
                "connector_slug, or cloud_file_id"
            )

        # Load the connection and its definition; tenant isolation is
        # enforced in the create endpoint, but the worker session also
        # has RLS set so cross-tenant leakage is impossible here.
        conn_result = await db.execute(
            sa_select(TenantConnection).where(
                TenantConnection.id == ds.connection_id,
                TenantConnection.deleted_at.is_(None),
            )
        )
        connection = conn_result.scalar_one_or_none()
        if connection is None:
            raise ValueError(
                f"TenantConnection {ds.connection_id} not found for "
                f"DataSource {ds.id}"
            )

        def_result = await db.execute(
            sa_select(ConnectorDefinition).where(
                ConnectorDefinition.id == connection.connector_definition_id,
            )
        )
        connector_def = def_result.scalar_one_or_none()
        if connector_def is None:
            raise ValueError(
                f"ConnectorDefinition missing for connection {connection.id}"
            )

        adapter = resolve_adapter(ds.connector_slug)
        drive_file = await adapter.download(
            connection=connection,
            connector_def=connector_def,
            file_id=ds.cloud_file_id,
            db=db,
        )

        # Enrich the DataSource with real metadata so the UI reflects the
        # actual downloaded file, not whatever placeholder the create call
        # carried.
        ds.filename = drive_file.filename
        ds.mime_type = drive_file.mime_type
        ds.file_size = drive_file.size

        return await self.process_bytes(
            drive_file.content,
            drive_file.filename,
            drive_file.mime_type,
        )

    @staticmethod
    def _validate_mime(data: bytes, filename: str, declared_mime: str) -> str:
        """Cross-check declared MIME type against magic bytes.

        Returns the magic-detected MIME if it differs from the declared one
        and the magic type is supported; otherwise returns the declared type.
        """
        try:
            import magic

            detected = magic.from_buffer(data[:8192], mime=True)
        except Exception:
            return declared_mime

        if detected and detected != declared_mime:
            logger.info(
                "mime_type_mismatch",
                filename=filename,
                declared=declared_mime,
                detected=detected,
            )
            # Prefer the magic-detected type if we have a parser for it
            if detected in DocumentProcessor.MIME_MAP:
                return detected

        return declared_mime
