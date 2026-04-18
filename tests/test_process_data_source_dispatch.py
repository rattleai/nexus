"""Tests for DocumentProcessor.process_data_source dispatch.

Verifies that the Celery extraction task routes each DataSource subtype to
the right extraction path — the bug it replaces (``processor.process(ds, db=db)``
against a ``process(file_key, tenant_id)`` signature) silently crashed every
non-UPLOAD ingest before this layer landed.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models.datasource import DataSource, DataSourceType
from app.docprocessor.base import ExtractionResult
from app.docprocessor.processor import DocumentProcessor


def _ds(**kwargs) -> DataSource:
    """Build an unsaved DataSource with sane defaults for dispatch tests."""
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "name": "test",
    }
    defaults.update(kwargs)
    ds = DataSource(**defaults)
    return ds


@pytest.mark.asyncio
async def test_upload_routes_to_s3_process():
    processor = DocumentProcessor()
    expected = ExtractionResult(source_type="pdf", source_name="file.pdf")
    processor.process = AsyncMock(return_value=expected)  # type: ignore[method-assign]
    ds = _ds(source_type=DataSourceType.UPLOAD, file_key="tenants/x/y/z.pdf")

    result = await processor.process_data_source(ds, db=MagicMock())

    assert result is expected
    processor.process.assert_called_once_with("tenants/x/y/z.pdf", ds.tenant_id)


@pytest.mark.asyncio
async def test_upload_without_file_key_raises():
    processor = DocumentProcessor()
    ds = _ds(source_type=DataSourceType.UPLOAD, file_key=None)

    with pytest.raises(ValueError, match="no file_key"):
        await processor.process_data_source(ds, db=MagicMock())


@pytest.mark.asyncio
async def test_url_routes_to_process_url():
    processor = DocumentProcessor()
    expected = ExtractionResult(source_type="url", source_name="https://example.com")
    processor.process_url = AsyncMock(return_value=expected)  # type: ignore[method-assign]
    ds = _ds(source_type=DataSourceType.URL, url="https://example.com/doc")

    result = await processor.process_data_source(ds, db=MagicMock())

    assert result is expected
    processor.process_url.assert_called_once_with(
        "https://example.com/doc", ds.tenant_id,
    )


@pytest.mark.asyncio
async def test_paste_is_noop_extraction():
    processor = DocumentProcessor()
    ds = _ds(source_type=DataSourceType.PASTE, name="paste-src")

    result = await processor.process_data_source(ds, db=MagicMock())

    assert result.source_type == "paste"
    assert result.source_name == "paste-src"


@pytest.mark.asyncio
async def test_cloud_drive_routes_through_adapter_and_enriches_metadata(monkeypatch):
    from app.connectors.drive import DriveFile

    processor = DocumentProcessor()

    # Stub the inner helper so we don't need a DB.
    drive_file = DriveFile(
        content=b"%PDF-fake",
        filename="report.pdf",
        mime_type="application/pdf",
        size=9,
    )

    expected = ExtractionResult(source_type="pdf", source_name="report.pdf")

    async def _fake_process_bytes(data, filename, mime_type):
        assert data == drive_file.content
        assert filename == "report.pdf"
        assert mime_type == "application/pdf"
        return expected

    async def _fake_inner(self, ds, db):
        # Replicate the metadata-enrichment side effect on the real code
        # path without touching the DB.
        ds.filename = drive_file.filename
        ds.mime_type = drive_file.mime_type
        ds.file_size = drive_file.size
        return await _fake_process_bytes(
            drive_file.content, drive_file.filename, drive_file.mime_type,
        )

    monkeypatch.setattr(
        DocumentProcessor, "_process_cloud_drive", _fake_inner, raising=True,
    )

    ds = _ds(
        source_type=DataSourceType.CLOUD_DRIVE,
        connection_id=uuid.uuid4(),
        connector_slug="dropbox",
        cloud_file_id="id:abc",
    )

    result = await processor.process_data_source(ds, db=MagicMock())

    assert result is expected
    assert ds.filename == "report.pdf"
    assert ds.mime_type == "application/pdf"
    assert ds.file_size == 9


@pytest.mark.asyncio
async def test_cloud_drive_missing_fields_raises():
    processor = DocumentProcessor()
    ds = _ds(
        source_type=DataSourceType.CLOUD_DRIVE,
        connection_id=None,
        connector_slug="dropbox",
        cloud_file_id="id:abc",
    )
    with pytest.raises(ValueError, match="missing connection_id"):
        await processor.process_data_source(ds, db=MagicMock())
