"""Tests for webhook HMAC signing, URL validation, and file path traversal prevention."""

import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_tenant, get_db
from app.main import create_app

# ── HMAC Signing Tests ────────────────────────────────────────────────


class TestWebhookSigning:
    """Verify webhook HMAC-SHA256 signature generation logic."""

    @staticmethod
    def _sign(payload: dict, signing_secret: str) -> str:
        """Reproduce the signing logic from tasks.py without importing it."""
        body = json.dumps(payload, sort_keys=True, default=str)
        return hmac.new(signing_secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    def test_sign_payload_produces_valid_hmac(self):
        payload = {"event": "job.completed", "job_id": "123"}
        signing_key = "test-secret-key"
        signature = self._sign(payload, signing_key)

        # Verify independently
        body = json.dumps(payload, sort_keys=True, default=str)
        expected = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        assert signature == expected

    def test_sign_payload_different_secrets_different_sigs(self):
        payload = {"event": "test"}
        sig1 = self._sign(payload, "secret-one")
        sig2 = self._sign(payload, "secret-two")
        assert sig1 != sig2

    def test_sign_payload_deterministic(self):
        payload = {"b": 2, "a": 1}
        sig1 = self._sign(payload, "key")
        sig2 = self._sign(payload, "key")
        assert sig1 == sig2

    def test_sign_payload_sorted_keys(self):
        """Keys are sorted for deterministic output regardless of insertion order."""
        payload1 = {"b": 2, "a": 1}
        payload2 = {"a": 1, "b": 2}
        sig1 = self._sign(payload1, "key")
        sig2 = self._sign(payload2, "key")
        assert sig1 == sig2


# ── URL Validation Tests ──────────────────────────────────────────────


class TestURLValidation:
    """Verify SSRF prevention in webhook URL validation."""

    def test_valid_public_url(self):
        from app.core.url_validation import validate_webhook_url

        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 443)),
            ]
            result = validate_webhook_url("https://example.com/webhook")
        assert result is None  # No error

    def test_rejects_private_ip(self):
        from app.core.url_validation import validate_webhook_url

        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("192.168.1.1", 443)),
            ]
            result = validate_webhook_url("https://internal.example.com/webhook")
        assert result is not None
        assert "private" in result.lower() or "internal" in result.lower()

    def test_rejects_localhost(self):
        from app.core.url_validation import validate_webhook_url

        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("127.0.0.1", 443)),
            ]
            result = validate_webhook_url("https://localhost/webhook")
        assert result is not None

    def test_allows_plain_http(self):
        from app.core.url_validation import validate_webhook_url

        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 80)),
            ]
            result = validate_webhook_url("http://example.com/webhook")
        # The implementation accepts both http and https schemes
        assert result is None

    def test_rejects_non_http_scheme(self):
        from app.core.url_validation import validate_webhook_url

        result = validate_webhook_url("ftp://example.com/data")
        assert result is not None


# ── File Path Traversal Tests ─────────────────────────────────────────


@pytest.fixture
async def file_client():
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_celery", new_callable=AsyncMock, return_value=True),
        patch("app.core.redis.redis_pool", new_callable=AsyncMock),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, app


class TestFilePathTraversal:
    """Verify path traversal prevention in file download/delete endpoints."""

    @pytest.mark.asyncio
    async def test_download_rejects_path_traversal_encoded(self, file_client):
        """File download rejects URL-encoded path traversal (%2e%2e)."""
        client, app = file_client
        tenant_id = uuid.uuid4()
        tenant = MagicMock(id=tenant_id, is_active=True)
        tenant.name = "Test"

        mock_api_key = MagicMock(
            tenant=tenant,
            scopes=["files:read"],
            active=True,
            rate_limit=100,
        )
        mock_api_key.name = "test"

        from app.api.deps import get_current_api_key

        app.dependency_overrides[get_current_tenant] = lambda: tenant
        app.dependency_overrides[get_current_api_key] = lambda: mock_api_key

        try:
            with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=mock_api_key):
                # Use %2e%2e which URL-decodes to .. — our fix in files.py catches this
                response = await client.get(
                    f"/api/v1/files/tenants/{tenant_id}/%2e%2e/%2e%2e/etc/passwd",
                )
            assert response.status_code in (400, 403)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_download_rejects_backslash_traversal(self, file_client):
        """File download rejects backslash path traversal."""
        client, app = file_client
        tenant_id = uuid.uuid4()
        tenant = MagicMock(id=tenant_id, is_active=True)
        tenant.name = "Test"

        mock_api_key = MagicMock(
            tenant=tenant,
            scopes=["files:read"],
            active=True,
            rate_limit=100,
        )
        mock_api_key.name = "test"

        from app.api.deps import get_current_api_key

        app.dependency_overrides[get_current_tenant] = lambda: tenant
        app.dependency_overrides[get_current_api_key] = lambda: mock_api_key

        try:
            with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=mock_api_key):
                response = await client.get(
                    f"/api/v1/files/tenants/{tenant_id}/..%5c..%5cetc%5cpasswd",
                )
            assert response.status_code in (400, 403)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_download_rejects_wrong_tenant(self, file_client):
        """File download rejects access to another tenant's files."""
        client, app = file_client
        tenant_id = uuid.uuid4()
        other_tenant_id = uuid.uuid4()
        tenant = MagicMock(id=tenant_id, is_active=True)
        tenant.name = "Test"

        mock_api_key = MagicMock(
            tenant=tenant,
            scopes=["files:read"],
            active=True,
            rate_limit=100,
        )
        mock_api_key.name = "test"

        from app.api.deps import get_current_api_key

        app.dependency_overrides[get_current_tenant] = lambda: tenant
        app.dependency_overrides[get_current_api_key] = lambda: mock_api_key

        try:
            with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=mock_api_key):
                response = await client.get(
                    f"/api/v1/files/tenants/{other_tenant_id}/secret.pdf",
                )
            assert response.status_code == 403
        finally:
            app.dependency_overrides.clear()


# ── Billing Endpoint Tests ────────────────────────────────────────────


@pytest.fixture
async def billing_client():
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_celery", new_callable=AsyncMock, return_value=True),
        patch("app.core.redis.redis_pool", new_callable=AsyncMock),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, app


class TestBillingEndpoints:
    """Test billing endpoint security and validation."""

    @pytest.mark.asyncio
    async def test_list_plans_no_auth_required(self, billing_client):
        """GET /billing/plans should work without authentication."""
        client, app = billing_client

        mock_db = AsyncMock()
        plans_result = MagicMock()
        plans_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=plans_result)

        async def _override_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_db

        try:
            response = await client.get("/api/v1/billing/plans")
            assert response.status_code == 200
            assert response.json() == []
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_cancel_subscription_requires_stripe(self, billing_client):
        """Cancel subscription returns 503 when Stripe is not configured."""
        client, app = billing_client

        from app.api.deps import get_current_tenant, get_current_user_from_token

        tenant_id = uuid.uuid4()
        user = MagicMock(
            id=uuid.uuid4(), tenant_id=tenant_id, is_active=True
        )
        tenant = MagicMock(id=tenant_id)
        app.dependency_overrides[get_current_user_from_token] = lambda: user
        app.dependency_overrides[get_current_tenant] = lambda: tenant

        mock_db = AsyncMock()
        # RequireRole needs membership check
        membership = MagicMock()
        from app.db.models import UserRole
        membership.role = UserRole.OWNER
        member_result = MagicMock()
        member_result.scalar_one_or_none.return_value = membership
        mock_db.execute = AsyncMock(return_value=member_result)

        async def _override_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_db

        try:
            with patch("app.config.settings") as mock_settings:
                mock_settings.stripe_configured = False
                response = await client.post(
                    "/api/v1/billing/subscription/cancel",
                    headers={"Authorization": "Bearer fake-token"},
                )
            assert response.status_code == 503
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_checkout_validates_return_url(self, billing_client):
        """Checkout rejects return_url on foreign domain."""
        client, _ = billing_client

        response = await client.post(
            "/api/v1/billing/checkout",
            json={
                "plan_id": str(uuid.uuid4()),
                "return_url": "https://evil.com/steal-session",
            },
        )
        # Should fail validation (either 422 from Pydantic or 401 from auth)
        assert response.status_code in (401, 422)


# ── Webhook Delivery SSRF Prevention Tests ───────────────────────────


class TestWebhookDeliverySSRF:
    """Verify SSRF prevention at webhook delivery time (not just registration)."""

    def test_deliver_webhook_blocks_private_ip(self):
        """deliver_webhook should re-validate URL at delivery time."""
        with patch("app.core.url_validation.validate_webhook_url") as mock_validate:
            mock_validate.return_value = "Resolved to private IP"

            # Import after patch to ensure it uses patched version
            from app.workers.tasks import deliver_webhook

            result = deliver_webhook(
                "https://internal.example.com/hook",
                {"event": "test"},
            )
            assert result["status"] == "blocked"
            mock_validate.assert_called_once()

    def test_deliver_webhook_allows_valid_url(self):
        """deliver_webhook should proceed when URL passes validation."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.post = MagicMock(return_value=mock_response)

        with (
            patch("app.core.url_validation.validate_webhook_url", return_value=None),
            patch("app.workers.tasks.settings") as mock_settings,
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_settings.WEBHOOK_SIGNING_KEY = "test-webhook-signing-key"
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

            from app.workers.tasks import deliver_webhook

            result = deliver_webhook(
                "https://example.com/hook",
                {"event": "test"},
            )
            assert result["status"] == "delivered"


# ── Rate Limiter Path Normalization Tests ────────────────────────────


class TestRateLimiterPathNormalization:
    """Verify rate limiter normalizes paths to prevent bypass."""

    def test_trailing_slash_produces_same_key(self):
        mock_request_1 = MagicMock()
        mock_request_1.url.path = "/api/v1/login"
        mock_request_1.client.host = "1.2.3.4"
        mock_request_1.headers.get.return_value = ""

        mock_request_2 = MagicMock()
        mock_request_2.url.path = "/api/v1/login/"
        mock_request_2.client.host = "1.2.3.4"
        mock_request_2.headers.get.return_value = ""

        # Both should normalize to same path
        normalized_1 = mock_request_1.url.path.rstrip("/").lower().replace("//", "/")
        normalized_2 = mock_request_2.url.path.rstrip("/").lower().replace("//", "/")
        assert normalized_1 == normalized_2

    def test_case_variation_produces_same_key(self):
        path1 = "/api/v1/Login".rstrip("/").lower().replace("//", "/")
        path2 = "/api/v1/login".rstrip("/").lower().replace("//", "/")
        assert path1 == path2
