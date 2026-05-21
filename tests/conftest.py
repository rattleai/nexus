from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def admin_client(app) -> AsyncGenerator[AsyncClient]:
    """Client with the admin key header set."""
    from app.config import settings

    transport = ASGITransport(app=app)
    admin_key = settings.ADMIN_KEY
    if not admin_key:
        # Use a deterministic test key when ADMIN_KEY is not configured
        admin_key = "test-admin-key-for-testing"
        settings.ADMIN_KEY = admin_key
    headers = {"X-Admin-Key": admin_key}
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as ac:
        yield ac


@pytest.fixture(autouse=True)
def mock_service_checks():
    """Prevent real DB, Redis, and storage connections in unit tests."""

    # Mock the async engine context manager for the RLS superuser check in lifespan.
    # Returns a non-superuser row so the check passes without a real DB.
    mock_conn = AsyncMock()
    mock_result = AsyncMock()
    mock_result.one_or_none.return_value = ("test_user", False)
    mock_conn.execute = AsyncMock(return_value=mock_result)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_engine_connect = AsyncMock(return_value=mock_conn)

    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_celery", new_callable=AsyncMock, return_value=True),
        patch("app.core.redis.redis_pool", new_callable=AsyncMock),
        patch("app.db.session.async_engine") as mock_engine,
    ):
        mock_engine.connect = mock_engine_connect
        yield
