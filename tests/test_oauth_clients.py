"""Tests for OAuth Client Credentials flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.oauth_clients import _generate_client_id, _generate_client_secret, _hash_secret


def test_generate_client_id():
    client_id = _generate_client_id()
    assert client_id.startswith("cad_")
    assert len(client_id) > 10


def test_generate_client_secret():
    secret = _generate_client_secret()
    assert len(secret) > 30


def test_hash_secret_deterministic():
    s1 = _hash_secret("test-secret")
    s2 = _hash_secret("test-secret")
    assert s1 == s2


def test_hash_secret_different_inputs():
    s1 = _hash_secret("secret-1")
    s2 = _hash_secret("secret-2")
    assert s1 != s2


@pytest.mark.asyncio
async def test_token_exchange_invalid_grant_type():
    """Test that non-client_credentials grant types are rejected."""
    from app.main import create_app

    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
    ):
        app = create_app()
        # Manually include the OAuth router since OAUTH_CLIENT_CREDENTIALS_ENABLED
        # is evaluated at module import time and may be False.
        from app.api.v1.oauth_clients import router as oauth_router

        app.include_router(oauth_router, prefix="/api/v1", tags=["oauth"])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "client_id": "test",
                    "client_secret": "test",
                },
            )
            assert response.status_code == 400
            assert "client_credentials" in response.json()["detail"]


@pytest.mark.asyncio
async def test_token_exchange_invalid_credentials():
    """Test that invalid client credentials are rejected."""
    from app.main import create_app

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def fake_db():
        yield mock_db

    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
    ):
        app = create_app()
        # Manually include the OAuth router since OAUTH_CLIENT_CREDENTIALS_ENABLED
        # is evaluated at module import time and may be False.
        from app.api.v1.oauth_clients import router as oauth_router

        app.include_router(oauth_router, prefix="/api/v1", tags=["oauth"])

        from app.api.deps import get_db
        app.dependency_overrides[get_db] = fake_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/oauth/token",
                json={
                    "grant_type": "client_credentials",
                    "client_id": "invalid",
                    "client_secret": "invalid",
                },
            )
            assert response.status_code == 401

        app.dependency_overrides.clear()
