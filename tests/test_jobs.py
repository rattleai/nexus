"""Tests for job management endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_tenant, get_db
from app.db.models import JobStatus
from app.main import create_app


def _make_tenant():
    return MagicMock(
        id=uuid.uuid4(),
        name="Test",
        slug="test",
        plan="free",
        is_active=True,
    )


def _make_job(tenant_id, **overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "type": "export",
        "status": JobStatus.PENDING,
        "webhook_url": None,
        "started_at": None,
        "completed_at": None,
        "error": None,
        "result": None,
        "created_at": now,
        "updated_at": now,
        "deleted_at": None,
        "version": 1,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@pytest.fixture
async def job_client():
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
        patch("app.core.redis.redis_pool", new_callable=AsyncMock),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, app


@pytest.mark.asyncio
async def test_create_job_requires_auth(job_client):
    client, _ = job_client
    response = await client.post("/api/v1/jobs", json={"type": "export"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_jobs_requires_auth(job_client):
    client, _ = job_client
    response = await client.get("/api/v1/jobs")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_job_not_found(job_client):
    client, app = job_client
    tenant = _make_tenant()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        response = await client.get(f"/api/v1/jobs/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cancel_completed_job(job_client):
    """Cancelling a completed job should return cancelled=false."""
    client, app = job_client
    tenant = _make_tenant()
    job = _make_job(tenant.id, status=JobStatus.COMPLETED)

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = job
    mock_db.execute.return_value = mock_result

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        response = await client.post(f"/api/v1/jobs/{job.id}/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["cancelled"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cancel_pending_job(job_client):
    """Cancelling a pending job should succeed."""
    client, app = job_client
    tenant = _make_tenant()
    job = _make_job(tenant.id, status=JobStatus.PENDING)
    job.status = JobStatus.PENDING  # make mutable

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = job
    mock_db.execute.return_value = mock_result
    mock_db.commit = AsyncMock()

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        response = await client.post(f"/api/v1/jobs/{job.id}/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["cancelled"] is True
    finally:
        app.dependency_overrides.clear()
