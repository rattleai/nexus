"""Tests for RequireUI access restriction and infrastructure scope enforcement.

Verifies that critical infrastructure endpoints (API keys, audit logs, OAuth
clients) are only accessible from JWT-authenticated UI sessions and that
infrastructure scopes cannot be granted to API keys or OAuth clients.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import RequireUI, get_current_tenant, get_db
from app.config import settings
from app.main import create_app


def _make_tenant():
    return MagicMock(
        id=uuid.uuid4(),
        name="Test",
        slug="test",
        plan="free",
        is_active=True,
        settings={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=None,
    )


def _make_user(tenant):
    return MagicMock(
        id=uuid.uuid4(),
        email="admin@example.com",
        tenant_id=tenant.id,
        is_active=True,
        deleted_at=None,
    )


def _make_api_key(tenant):
    return MagicMock(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        key_hash="fake_hash",
        name="test-key",
        scopes=["jobs:read", "jobs:write"],
        active=True,
        tenant=tenant,
    )


@pytest.fixture
async def test_app():
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


# ── API key endpoints reject API key auth ────────────────


@pytest.mark.asyncio
async def test_api_keys_create_rejects_api_key_auth(test_app):
    """API key creation must reject X-API-Key auth (UI-only)."""
    client, app = test_app
    tenant = _make_tenant()
    api_key = _make_api_key(tenant)

    mock_db = AsyncMock()
    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        # Simulate API key auth by providing X-API-Key without JWT
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=api_key):
            response = await client.post(
                "/api/v1/api-keys",
                json={"name": "escalation-key"},
                headers={"X-API-Key": "sk_test_fake"},
            )
        assert response.status_code == 403
        assert "only accessible from the application UI" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_keys_list_rejects_api_key_auth(test_app):
    """API key listing must reject X-API-Key auth (UI-only)."""
    client, app = test_app
    tenant = _make_tenant()
    api_key = _make_api_key(tenant)

    mock_db = AsyncMock()
    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=api_key):
            response = await client.get(
                "/api/v1/api-keys",
                headers={"X-API-Key": "sk_test_fake"},
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_keys_revoke_rejects_api_key_auth(test_app):
    """API key revocation must reject X-API-Key auth (UI-only)."""
    client, app = test_app
    tenant = _make_tenant()
    api_key = _make_api_key(tenant)

    mock_db = AsyncMock()
    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=api_key):
            response = await client.delete(
                f"/api/v1/api-keys/{uuid.uuid4()}",
                headers={"X-API-Key": "sk_test_fake"},
            )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_keys_no_auth_returns_401(test_app):
    """API key endpoints require authentication (401 without any auth)."""
    client, _ = test_app
    response = await client.post("/api/v1/api-keys", json={"name": "my-key"})
    # RequireUI returns 403 when no JWT is present
    assert response.status_code in (401, 403)


# ── Infrastructure scope denylist ────────────────────────


@pytest.mark.asyncio
async def test_create_api_key_rejects_infrastructure_scopes(test_app):
    """API key creation must reject infrastructure scopes."""
    client, app = test_app
    tenant = _make_tenant()
    user = _make_user(tenant)

    mock_db = AsyncMock()
    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        # Simulate JWT auth by patching _resolve_user_from_jwt
        with patch("app.api.deps._resolve_user_from_jwt", new_callable=AsyncMock, return_value=user):
            response = await client.post(
                "/api/v1/api-keys",
                json={"name": "bad-key", "scopes": ["jobs:read", "api-keys:write"]},
                headers={"Authorization": "Bearer fake_jwt"},
            )
        assert response.status_code == 422
        assert "infrastructure scopes" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_validate_scopes_allows_safe_scopes():
    """_validate_scopes allows non-infrastructure scopes."""
    from app.api.v1.api_keys import _validate_scopes

    # Should not raise
    result = _validate_scopes(["jobs:read", "files:read", "ai:write"])
    assert result == ["jobs:read", "files:read", "ai:write"]


def test_validate_scopes_rejects_infrastructure():
    """_validate_scopes rejects infrastructure scopes."""
    from app.api.v1.api_keys import _validate_scopes

    with pytest.raises(Exception) as exc_info:
        _validate_scopes(["jobs:read", "api-keys:write"])
    assert "infrastructure scopes" in str(exc_info.value.detail)


# ── Audit log access restriction ─────────────────────────


@pytest.mark.asyncio
async def test_audit_logs_reject_api_key_auth(test_app):
    """Audit log endpoint must reject API key auth (UI-only)."""
    client, app = test_app
    tenant = _make_tenant()
    api_key = _make_api_key(tenant)

    mock_db = AsyncMock()
    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=api_key):
            response = await client.get(
                "/api/v1/audit-logs",
                headers={"X-API-Key": "sk_test_fake"},
            )
        assert response.status_code == 403
        assert "only accessible from the application UI" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ── MCP bridge does not expose api-keys ──────────────────


def test_mcp_bridge_excludes_api_keys_tag():
    """MCP bridge allowlist must not include api-keys tag."""
    from app.mcp.api_bridge import _ALLOWED_TAGS

    assert "api-keys" not in _ALLOWED_TAGS


def test_mcp_bridge_excludes_api_keys_path():
    """MCP bridge path allowlist must not include api-keys prefix."""
    from app.mcp.api_bridge import _ALLOWED_PATH_PREFIXES

    for prefix in _ALLOWED_PATH_PREFIXES:
        assert "api-keys" not in prefix


def test_mcp_bridge_excludes_infrastructure_tags():
    """MCP bridge must never expose infrastructure tags."""
    from app.mcp.api_bridge import _ALLOWED_TAGS

    infrastructure_tags = {"auth", "admin", "tenants", "api-keys", "oauth", "webauthn", "audit", "push", "sync"}
    overlap = _ALLOWED_TAGS & infrastructure_tags
    assert not overlap, f"MCP bridge exposes infrastructure tags: {overlap}"


def test_mcp_bridge_operation_filter_rejects_infrastructure():
    """The operation filter must reject infrastructure paths and tags."""
    from app.mcp.api_bridge import _should_include_operation

    # api-keys routes should be rejected
    assert not _should_include_operation("create_api_key", "/api/v1/api-keys", ["api-keys"])
    # auth routes should be rejected
    assert not _should_include_operation("login", "/api/v1/auth/login", ["auth"])
    # admin routes should be rejected
    assert not _should_include_operation("list_users", "/api/v1/admin/users", ["admin"])
    # tenant routes should be rejected
    assert not _should_include_operation("create_tenant", "/api/v1/tenants", ["tenants"])
    # oauth routes should be rejected
    assert not _should_include_operation("create_oauth_client", "/api/v1/oauth/clients", ["oauth"])

    # Safe routes should be allowed (use non-handwritten operation_ids)
    assert _should_include_operation("list_jobs_v2", "/api/v1/jobs", ["jobs"])
    assert _should_include_operation("upload_file_v2", "/api/v1/files", ["files"])
    assert _should_include_operation("ai_complete_v2", "/api/v1/ai/completions", ["ai"])


# ── Infrastructure scopes config ─────────────────────────


def test_infrastructure_scopes_defined():
    """INFRASTRUCTURE_SCOPES must be defined and non-empty."""
    assert settings.INFRASTRUCTURE_SCOPES
    assert isinstance(settings.INFRASTRUCTURE_SCOPES, frozenset)
    assert "api-keys:read" in settings.INFRASTRUCTURE_SCOPES
    assert "api-keys:write" in settings.INFRASTRUCTURE_SCOPES
    assert "audit:read" in settings.INFRASTRUCTURE_SCOPES


def test_infrastructure_scopes_subset_of_valid():
    """Every infrastructure scope must be a valid scope."""
    invalid = settings.INFRASTRUCTURE_SCOPES - set(settings.VALID_SCOPES)
    assert not invalid, f"Infrastructure scopes not in VALID_SCOPES: {invalid}"


# ── PII masking in MCP team tool ─────────────────────────


def test_mask_email_standard():
    """Standard email addresses should be masked."""
    from app.mcp.tools.team import _mask_email

    assert _mask_email("john@example.com") == "j***n@example.com"
    assert _mask_email("alice@corp.io") == "a***e@corp.io"


def test_mask_email_short_local():
    """Short local parts should be handled gracefully."""
    from app.mcp.tools.team import _mask_email

    assert _mask_email("ab@example.com") == "a***b@example.com"
    assert _mask_email("a@example.com") == "a***@example.com"


def test_mask_email_none():
    """None and empty values should return None."""
    from app.mcp.tools.team import _mask_email

    assert _mask_email(None) is None
    assert _mask_email("") is None
    assert _mask_email("no-at-sign") is None


@pytest.mark.asyncio
async def test_team_list_members_masks_email():
    """MCP team_list_members must return masked emails."""
    from app.mcp.tools.team import team_list_members

    tenant = MagicMock(id=uuid.uuid4())
    mock_db = AsyncMock()

    mock_member = MagicMock(
        user_id=uuid.uuid4(),
        role=MagicMock(value="admin"),
        user=MagicMock(email="alice@example.com", display_name="Alice"),
        created_at=MagicMock(isoformat=lambda: "2026-01-01T00:00:00"),
    )

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_member]
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await team_list_members(tenant=tenant, db=mock_db)

    assert len(result) == 1
    assert result[0]["email"] == "a***e@example.com"
    assert result[0]["name"] == "Alice"
    assert result[0]["role"] == "admin"
    # Verify full email is NOT exposed
    assert "alice@example.com" not in str(result)
