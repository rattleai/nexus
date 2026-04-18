"""Security tests for PR #53: AI agent + configuration integration.

Covers: OAuth state validation, SSRF protection, tenant isolation,
LIKE injection, redirect URI validation, token decryption, cloud drive
query injection, file-size limits, magic-byte MIME validation, and
resource-ID validation.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import pytest

# ── Helpers ──────────────────────────────────────────────────────────


def _make_tenant(tenant_id=None):
    return MagicMock(id=tenant_id or uuid.uuid4(), name="Test", slug="test", plan="free", is_active=True)


# ── escape_like ──────────────────────────────────────────────────────


class TestEscapeLike:
    def test_normal_string(self):
        from app.core.query_utils import escape_like

        assert escape_like("hello world") == "hello world"

    def test_percent_escaped(self):
        from app.core.query_utils import escape_like

        assert escape_like("100%") == r"100\%"

    def test_underscore_escaped(self):
        from app.core.query_utils import escape_like

        assert escape_like("a_b") == r"a\_b"

    def test_backslash_escaped(self):
        from app.core.query_utils import escape_like

        assert escape_like(r"a\b") == r"a\\b"

    def test_combined_metacharacters(self):
        from app.core.query_utils import escape_like

        assert escape_like("%_\\") == "\\%\\_\\\\"


# ── SSRF Protection ─────────────────────────────────────────────────


class TestWebParserSSRF:
    @pytest.mark.asyncio
    async def test_rejects_private_ip(self):
        from app.docprocessor.parsers.web_parser import WebParser

        parser = WebParser()
        with patch(
            "app.core.url_validation.validate_webhook_url_async", new_callable=AsyncMock, return_value="URL blocked"
        ):
            result = await parser.parse_url("http://169.254.169.254/latest/meta-data/")
        assert "error" in result.metadata
        assert "blocked" in result.metadata["error"].lower()

    @pytest.mark.asyncio
    async def test_allows_valid_url(self):
        """Ensure valid URLs pass the SSRF check (content validation may still fail)."""
        from app.docprocessor.parsers.web_parser import WebParser

        parser = WebParser()
        # Mock SSRF check as passing, but the actual fetch will fail in test
        with patch("app.core.url_validation.validate_webhook_url_async", new_callable=AsyncMock, return_value=None):
            # The fetch itself may fail in tests since we're not mocking httpx,
            # but the SSRF check should pass
            result = await parser.parse_url("https://example.com")
            # Either succeeds or fails at fetch, but NOT at SSRF check
            if "error" in result.metadata:
                assert "blocked" not in result.metadata["error"].lower()


# ── UUID Validation ──────────────────────────────────────────────────


class TestConfiguratorValidation:
    def test_parse_uuid_valid(self):
        from app.mcp.tools.configurator import _parse_uuid

        uid = uuid.uuid4()
        result = _parse_uuid(str(uid), "test_field")
        assert result == uid

    def test_parse_uuid_invalid(self):
        from app.mcp.tools.configurator import _parse_uuid

        result = _parse_uuid("not-a-uuid", "test_field")
        assert isinstance(result, dict)
        assert "error" in result

    def test_parse_uuid_empty(self):
        from app.mcp.tools.configurator import _parse_uuid

        result = _parse_uuid("", "test_field")
        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_config_get_product_invalid_uuid(self):
        from app.mcp.tools.configurator import config_get_product

        tenant = _make_tenant()
        db = AsyncMock()
        result = await config_get_product("not-a-uuid", tenant=tenant, db=db)
        assert "error" in result
        assert "Invalid product_id" in result["error"]

    @pytest.mark.asyncio
    async def test_config_create_product_invalid_family_id(self):
        from app.mcp.tools.configurator import config_create_product

        tenant = _make_tenant()
        db = AsyncMock()
        result = await config_create_product(
            name="Test",
            slug="test",
            family_id="bad-uuid",
            tenant=tenant,
            db=db,
        )
        assert "error" in result
        assert "Invalid family_id" in result["error"]


# ── Enum Validation ──────────────────────────────────────────────────


class TestEnumValidation:
    @pytest.mark.asyncio
    async def test_config_list_products_invalid_status(self):
        from app.mcp.tools.configurator import config_list_products

        tenant = _make_tenant()
        db = AsyncMock()
        result = await config_list_products(status="nonexistent_status", tenant=tenant, db=db)
        assert "error" in result
        assert "Invalid status" in result["error"]


# ── CharacteristicType Bug Fix ───────────────────────────────────────


class TestCharacteristicTypeFix:
    def test_import_characteristic_type(self):
        """Verify the CharType -> CharacteristicType fix by importing the module."""
        # This would have crashed pre-fix due to importing non-existent CharType
        from app.mcp.tools import configurator

        assert hasattr(configurator, "config_create_characteristic")


# ── Error Sanitization ───────────────────────────────────────────────


class TestErrorSanitization:
    def test_sanitize_api_key(self):
        from app.agents.executor import _sanitize_error

        exc = Exception("Failed with key sk-abc123xyz")
        result = _sanitize_error(exc)
        assert "sk-abc123" not in result
        assert "[REDACTED]" in result

    def test_sanitize_aws_key(self):
        from app.agents.executor import _sanitize_error

        exc = Exception("Auth failed: AKIAIOSFODNN7EXAMPLE")
        result = _sanitize_error(exc)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "AWS_KEY_REDACTED" in result

    def test_sanitize_db_url(self):
        from app.agents.executor import _sanitize_error

        exc = Exception("Connection to postgresql://user:pass@host/db failed")
        result = _sanitize_error(exc)
        assert "user:pass" not in result
        assert "DB_URL_REDACTED" in result

    def test_sanitize_password(self):
        from app.agents.executor import _sanitize_error

        exc = Exception("password=s3cret123 token=abc")
        result = _sanitize_error(exc)
        assert "s3cret123" not in result

    def test_truncation(self):
        from app.agents.executor import _sanitize_error

        exc = Exception("x" * 5000)
        result = _sanitize_error(exc)
        assert len(result) == 2000


# ── CSV Formula Injection ────────────────────────────────────────────


class TestCSVFormulaSanitization:
    @pytest.mark.asyncio
    async def test_formula_cells_prefixed(self):
        from app.docprocessor.parsers.csv_parser import CSVParser

        csv_content = b"name,value\n=CMD(),100\n+malicious,200\n@sum,300\n-evil,400\nnormal,500"
        parser = CSVParser()
        result = await parser.parse(file_bytes=csv_content, filename="test.csv")

        # Check that formula characters were prefixed with '
        for table in result.tables:
            for row in table.rows:
                for cell in row:
                    if cell and cell.startswith("'"):
                        # This is a sanitized formula cell - good
                        pass
                    else:
                        # Normal cell should not start with formula chars
                        assert not cell or cell[0] not in "=+@-" or cell == "normal"

    @pytest.mark.asyncio
    async def test_normal_cells_untouched(self):
        from app.docprocessor.parsers.csv_parser import CSVParser

        csv_content = b"name,value\nhello,world\nfoo,bar"
        parser = CSVParser()
        result = await parser.parse(file_bytes=csv_content, filename="test.csv")
        assert result.tables[0].rows[0] == ["hello", "world"]


# ── JSON Parser Depth Limit ──────────────────────────────────────────


class TestJSONParserDepthLimit:
    def test_deep_nesting_truncated(self):
        from app.docprocessor.parsers.json_parser import JSONParser

        # Build a deeply nested dict (25 levels)
        d: dict = {"leaf": "value"}
        for _i in range(25):
            d = {"level": d}

        result = JSONParser._flatten_dict(d)
        # Should not recurse beyond 20 levels - should have JSON-serialized value
        assert len(result) > 0
        # The key should stop nesting at depth 20
        max_dots = max(k.count(".") for k in result)
        assert max_dots <= 20


# ── Token Decryption Fallback ────────────────────────────────────────


class TestTokenDecryptionFallback:
    @pytest.mark.asyncio
    async def test_bearer_decrypt_failure_returns_error(self):
        from app.agents.tool_registry import ToolRegistry

        registry = ToolRegistry()
        tool = MagicMock()
        tool.tool_name = "test_tool"
        tool.endpoint_url = "https://example.com/api"
        tool.auth_config = {"type": "bearer", "token": "encrypted_garbage"}
        tool.tenant_id = uuid.uuid4()

        with patch("app.core.url_validation.validate_url"):
            with patch("app.core.encryption.decrypt", side_effect=ValueError("bad data")):
                result = await registry._invoke_external(tool, {"arg": "value"})

        assert "error" in result
        assert "invalid authentication" in result["error"].lower()


# ── Cloud Drive Query Injection ─────────────────────────────────────


# TestOneDriveQueryEscaping, TestGoogleDriveQueryEscaping, and
# TestCloudDriveErrorIsolation were removed with PR #67: the legacy
# app/integrations/cloud_drives/ module is deleted in favor of the
# unified connector framework. Equivalent coverage for the new drive
# adapters lives under tests/connectors/ (OAuth escaping is enforced
# by the broker layer; CloudDriveError is replaced by DriveAdapterError).


# ── Parser File Size Limits ─────────────────────────────────────────


class TestParserFileSizeLimits:
    @pytest.mark.asyncio
    async def test_pdf_rejects_oversized_file(self):
        from app.docprocessor.parsers.pdf_parser import PDFParser

        parser = PDFParser()
        huge_bytes = b"\x00" * (PDFParser.MAX_FILE_SIZE + 1)
        result = await parser.parse(file_bytes=huge_bytes, filename="huge.pdf")
        assert "error" in result.metadata
        assert "too large" in result.metadata["error"].lower()

    @pytest.mark.asyncio
    async def test_excel_rejects_oversized_file(self):
        from app.docprocessor.parsers.excel_parser import ExcelParser

        parser = ExcelParser()
        huge_bytes = b"\x00" * (ExcelParser.MAX_FILE_SIZE + 1)
        result = await parser.parse(file_bytes=huge_bytes, filename="huge.xlsx")
        assert "error" in result.metadata
        assert "too large" in result.metadata["error"].lower()

    @pytest.mark.asyncio
    async def test_word_rejects_oversized_file(self):
        from app.docprocessor.parsers.word_parser import WordParser

        parser = WordParser()
        huge_bytes = b"\x00" * (WordParser.MAX_FILE_SIZE + 1)
        result = await parser.parse(file_bytes=huge_bytes, filename="huge.docx")
        assert "error" in result.metadata
        assert "too large" in result.metadata["error"].lower()


# ── MIME Magic Byte Validation ──────────────────────────────────────


class TestMIMEMagicValidation:
    def test_mime_mismatch_prefers_magic_type(self):
        import sys

        from app.docprocessor.processor import DocumentProcessor

        processor = DocumentProcessor()
        pdf_header = b"%PDF-1.4 fake content"
        mock_magic = MagicMock()
        mock_magic.from_buffer = MagicMock(return_value="application/pdf")
        with patch.dict(sys.modules, {"magic": mock_magic}):
            result = processor._validate_mime(pdf_header, "fake.csv", "text/csv")
        assert result == "application/pdf"

    def test_mime_match_keeps_declared(self):
        import sys

        from app.docprocessor.processor import DocumentProcessor

        processor = DocumentProcessor()
        mock_magic = MagicMock()
        mock_magic.from_buffer = MagicMock(return_value="application/pdf")
        with patch.dict(sys.modules, {"magic": mock_magic}):
            result = processor._validate_mime(b"data", "file.pdf", "application/pdf")
        assert result == "application/pdf"

    def test_magic_unavailable_falls_back(self):
        import sys

        from app.docprocessor.processor import DocumentProcessor

        processor = DocumentProcessor()
        # Simulate magic not being importable
        with patch.dict(sys.modules, {"magic": None}):
            result = processor._validate_mime(b"data", "file.csv", "text/csv")
        assert result == "text/csv"


# ── Tenant Chunk Deletion Filter ───────────────────────────────────


class TestChunkDeletionTenantFilter:
    """Verify that chunk bulk deletion includes tenant filter."""

    def test_datasources_reprocess_includes_tenant_filter(self):
        """Static check that the reprocess endpoint filters chunks by tenant."""
        import inspect

        from app.api.v1 import datasources

        source = inspect.getsource(datasources)
        # The delete(DataSourceChunk) call must include tenant_id
        assert "DataSourceChunk.tenant_id == tenant.id" in source


# ── ORM Index Naming ────────────────────────────────────────────────


class TestORMIndexNaming:
    """Verify ORM index names match migration index names."""

    def test_provenance_index_names_match_migration(self):
        from app.db.models.datasource import ConfigItemProvenance

        index_names = {idx.name for idx in ConfigItemProvenance.__table__.indexes}
        # These names must match what migration 0019 created
        assert "ix_config_provenance_tenant_entity" in index_names
        assert "ix_config_provenance_tenant_source" in index_names
