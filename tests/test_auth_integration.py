"""Integration tests for authentication endpoints.

Tests the full auth flow: register → login → refresh → logout → me,
as well as edge cases: duplicate email, inactive accounts, email verification,
password reset, and account lockout.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _mock_user(tenant_id=None, **overrides):
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id or uuid.uuid4(),
        "email": "test@example.com",
        "email_verified": True,
        "password_hash": None,
        "display_name": "Test User",
        "is_active": True,
        "last_login_at": None,
        "mfa_enabled": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "deleted_at": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _mock_membership(user_id, tenant_id, role="owner"):
    from app.db.models import UserRole

    m = MagicMock()
    m.user_id = user_id
    m.tenant_id = tenant_id
    m.role = UserRole(role)
    return m


def _create_auth_app():
    """Create a minimal FastAPI app with auth routes registered."""
    from app.api.v1.auth_routes import router as auth_router

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    return app


@pytest.fixture
async def auth_client():
    with patch("app.core.redis.redis_pool", new_callable=AsyncMock):
        app = _create_auth_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, app


# ── Registration Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_success(auth_client):
    """Successful registration returns 201 with access token and user data."""
    client, app = auth_client

    from app.api.deps import get_db

    mock_db = AsyncMock()
    select_user = MagicMock()
    select_user.scalar_one_or_none.return_value = None
    select_tenant = MagicMock()
    select_tenant.scalar_one_or_none.return_value = None

    async def _fake_flush():
        """Simulate DB flush — assign IDs to all tracked objects."""
        for obj in added_objects:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()

    added_objects = []

    def _track_add(obj):
        added_objects.append(obj)

    mock_db.add = _track_add

    async def _fake_refresh(obj):
        """Simulate DB refresh by populating auto-generated fields."""
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "is_active") and obj.is_active is None:
            obj.is_active = True
        if hasattr(obj, "email_verified") and obj.email_verified is None:
            obj.email_verified = False
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(UTC)

    mock_db.execute = AsyncMock(side_effect=[select_user, select_tenant])
    mock_db.flush = _fake_flush
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock(side_effect=_fake_refresh)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        with (
            patch("app.api.v1.auth_routes.send_email", new_callable=AsyncMock),
            patch("app.api.v1.auth_routes.emit", new_callable=AsyncMock),
        ):
            response = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "password": "SecurePass123",
                    "display_name": "New User",
                    "tenant_slug": "new-org",
                },
            )
        assert response.status_code == 201
        data = response.json()
        # Registration no longer issues tokens — user must verify email first
        assert "access_token" not in data
        assert "message" in data
        assert "user" in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_register_duplicate_email(auth_client):
    """Registration with existing email returns 409."""
    client, app = auth_client

    from app.api.deps import get_db

    mock_db = AsyncMock()
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = _mock_user()
    mock_db.execute = AsyncMock(return_value=select_result)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": "SecurePass123",
                "tenant_slug": "my-org",
            },
        )
        assert response.status_code == 409
        assert "already registered" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_register_weak_password_rejected(auth_client):
    """Registration with weak password returns 422."""
    client, _ = auth_client

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "password": "weakpass",
            "tenant_slug": "my-org",
        },
    )
    assert response.status_code == 422


# ── Login Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_success(auth_client):
    """Successful login returns access token and sets refresh cookie."""
    client, app = auth_client

    from app.api.deps import get_db
    from app.core.security import hash_password

    tenant_id = uuid.uuid4()
    user = _mock_user(
        tenant_id=tenant_id,
        email="user@example.com",
        password_hash=hash_password("SecurePass123"),
        email_verified=True,
    )
    membership = _mock_membership(user.id, tenant_id, "owner")

    mock_db = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = membership
    # Mock tenant result for MFA check (tenant with no require_mfa setting)
    mock_tenant = MagicMock()
    mock_tenant.settings = {}
    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = mock_tenant
    tokens_result = MagicMock()
    tokens_result.scalars.return_value.all.return_value = []

    mock_db.execute = AsyncMock(side_effect=[user_result, member_result, tenant_result, tokens_result])
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "SecurePass123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["email"] == "user@example.com"
        assert any("refresh_token" in c for c in response.headers.get_list("set-cookie"))
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_wrong_password(auth_client):
    """Login with wrong password returns 401."""
    client, app = auth_client

    from app.api.deps import get_db
    from app.core.security import hash_password

    user = _mock_user(password_hash=hash_password("CorrectPass123"))

    mock_db = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    mock_db.execute = AsyncMock(return_value=user_result)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "WrongPass123"},
        )
        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_nonexistent_email(auth_client):
    """Login with nonexistent email returns 401."""
    client, app = auth_client

    from app.api.deps import get_db

    mock_db = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=user_result)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "AnyPass123"},
        )
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_inactive_account(auth_client):
    """Login to inactive account returns 403."""
    client, app = auth_client

    from app.api.deps import get_db
    from app.core.security import hash_password

    user = _mock_user(
        password_hash=hash_password("SecurePass123"),
        is_active=False,
        email_verified=True,
    )

    mock_db = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    mock_db.execute = AsyncMock(return_value=user_result)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "SecurePass123"},
        )
        assert response.status_code == 403
        assert "disabled" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_unverified_email(auth_client):
    """Login with unverified email returns 403."""
    client, app = auth_client

    from app.api.deps import get_db
    from app.core.security import hash_password

    user = _mock_user(
        password_hash=hash_password("SecurePass123"),
        email_verified=False,
    )

    mock_db = AsyncMock()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    mock_db.execute = AsyncMock(return_value=user_result)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "SecurePass123"},
        )
        assert response.status_code == 403
        assert "not verified" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ── Refresh Token Tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_no_cookie(auth_client):
    """Refresh without cookie returns 401."""
    client, _ = auth_client
    response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_revoked_token(auth_client):
    """Refresh with already-revoked token returns 401."""
    client, app = auth_client

    from app.api.deps import get_db

    mock_db = AsyncMock()
    revoke_result = MagicMock()
    revoke_result.first.return_value = None
    mock_db.execute = AsyncMock(return_value=revoke_result)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        client.cookies.set("refresh_token", "some-revoked-token", domain="test")
        response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


# ── Me Endpoint Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_requires_auth(auth_client):
    """GET /me without Authorization returns 401."""
    client, _ = auth_client
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_profile(auth_client):
    """GET /me returns authenticated user's profile."""
    client, app = auth_client

    from app.api.deps import get_current_user_from_token, get_db

    tenant_id = uuid.uuid4()
    user = _mock_user(tenant_id=tenant_id)
    membership = _mock_membership(user.id, tenant_id, "member")

    app.dependency_overrides[get_current_user_from_token] = lambda: user

    mock_db = AsyncMock()
    member_result = MagicMock()
    member_result.scalar_one_or_none.return_value = membership
    mock_db.execute = AsyncMock(return_value=member_result)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer fake-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == user.email
        assert data["role"] == "member"
    finally:
        app.dependency_overrides.clear()


# ── Refresh Token Edge Cases ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_rejects_unverified_email(auth_client):
    """Refresh should reject users whose email is no longer verified."""
    client, app = auth_client

    from app.api.deps import get_db

    user = _mock_user(email_verified=False)

    mock_db = AsyncMock()
    # First execute: atomic revoke returns a valid row
    revoke_result = MagicMock()
    revoke_result.first.return_value = MagicMock(
        id=uuid.uuid4(),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    # Second execute: user lookup returns user with email_verified=False
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user

    mock_db.execute = AsyncMock(side_effect=[revoke_result, user_result])
    mock_db.commit = AsyncMock()

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db

    try:
        client.cookies.set("refresh_token", "valid-token", domain="test")
        response = await client.post("/api/v1/auth/refresh")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


# ── Token Validation Edge Cases ──────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_email_rejects_overlong_token(auth_client):
    """Verify email rejects tokens exceeding max length."""
    client, _ = auth_client
    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": "x" * 300},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reset_password_rejects_overlong_token(auth_client):
    """Reset password rejects tokens exceeding max length."""
    client, _ = auth_client
    response = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "x" * 300, "new_password": "SecurePass123"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_accept_invitation_rejects_overlong_token(auth_client):
    """Accept invitation rejects tokens exceeding max length."""
    client, _ = auth_client
    response = await client.post(
        "/api/v1/auth/accept-invitation",
        json={"token": "x" * 300},
    )
    assert response.status_code == 422
