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


class TestOneDriveQueryEscaping:
    @pytest.mark.asyncio
    async def test_search_query_is_url_encoded(self):
        """Verify that special chars in OneDrive search are URL-encoded."""
        from app.integrations.cloud_drives.onedrive import OneDriveConnector

        connector = OneDriveConnector()
        malicious_query = "test') or true or ('"

        # Mock httpx to capture the URL
        captured_urls: list[str] = []

        class _FakeResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"value": []}

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def get(self, url, **kw):
                captured_urls.append(url)
                return _FakeResp()

        with patch("httpx.AsyncClient", return_value=_FakeClient()):
            await connector.list_files("fake_token", query=malicious_query)

        assert len(captured_urls) == 1
        # The raw malicious string should NOT appear in the URL
        assert malicious_query not in captured_urls[0]
        # The URL-encoded version should be present
        assert quote(malicious_query) in captured_urls[0]

    def test_folder_id_rejects_path_traversal(self):
        """Validate that folder_id with path traversal chars is rejected."""
        from app.integrations.cloud_drives.base import validate_resource_id

        with pytest.raises(ValueError, match="Invalid folder_id"):
            validate_resource_id("../../../etc/passwd", "folder_id")

    def test_folder_id_allows_valid_id(self):
        from app.integrations.cloud_drives.base import validate_resource_id

        # Should not raise
        validate_resource_id("ABC123-def_456.78", "folder_id")

    def test_folder_id_rejects_empty(self):
        from app.integrations.cloud_drives.base import validate_resource_id

        with pytest.raises(ValueError):
            validate_resource_id("", "folder_id")


class TestGoogleDriveQueryEscaping:
    @pytest.mark.asyncio
    async def test_single_quotes_escaped_in_search(self):
        """Verify that single quotes in Google Drive search are escaped."""
        from app.integrations.cloud_drives.google_drive import GoogleDriveConnector

        connector = GoogleDriveConnector()
        malicious_query = "file' or 1=1 or name contains '"

        captured_params: list[dict] = []

        class _FakeResp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"files": []}

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def get(self, url, headers=None, params=None):
                if params:
                    captured_params.append(params)
                return _FakeResp()

        with patch("httpx.AsyncClient", return_value=_FakeClient()):
            await connector.list_files("fake_token", query=malicious_query)

        assert len(captured_params) >= 1
        q_value = captured_params[0]["q"]
        # The raw unescaped single quote should not appear unescaped
        assert "file' or" not in q_value
        # The escaped version should be present
        assert "file\\' or" in q_value


class TestCloudDriveErrorIsolation:
    @pytest.mark.asyncio
    async def test_onedrive_raises_cloud_drive_error(self):
        """Verify that httpx errors are wrapped in CloudDriveError."""
        import httpx

        from app.integrations.cloud_drives.base import CloudDriveError
        from app.integrations.cloud_drives.onedrive import OneDriveConnector

        connector = OneDriveConnector()

        class _FakeResp:
            status_code = 403
            request = httpx.Request("GET", "https://graph.microsoft.com/test")

            def raise_for_status(self):
                raise httpx.HTTPStatusError("Forbidden", request=self.request, response=self)  # type: ignore[arg-type]

            def json(self):
                return {}

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def get(self, url, **kw):
                return _FakeResp()

        with patch("httpx.AsyncClient", return_value=_FakeClient()):
            with pytest.raises(CloudDriveError) as exc_info:
                await connector.list_files("fake_token")
            assert exc_info.value.status_code == 403
            assert exc_info.value.provider == "onedrive"


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
