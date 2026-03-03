from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from cadprice.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def mock_service_checks():
    """Prevent real DB, Redis, and storage connections in unit tests."""
    with (
        patch("cadprice.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("cadprice.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
    ):
        yield
