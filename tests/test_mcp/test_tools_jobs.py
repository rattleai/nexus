"""Tests for MCP job tools."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.shared.exceptions import McpError

from app.db.models import JobStatus
from app.mcp.tools.jobs import job_cancel, job_create, job_get, job_list


def _make_tenant():
    return MagicMock(id=uuid.uuid4(), name="Test", is_active=True)


def _make_job(tenant_id, **overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "type": "export",
        "status": JobStatus.PENDING,
        "payload": {},
        "result": None,
        "error": None,
        "created_at": now,
        "completed_at": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@pytest.mark.asyncio
async def test_job_create():
    tenant = _make_tenant()
    mock_db = AsyncMock()

    job = _make_job(tenant.id)
    mock_db.refresh = AsyncMock(return_value=None)

    with patch("app.mcp.tools.jobs.Job") as mock_job_cls:
        mock_job_cls.return_value = job
        result = await job_create(job_type="export", payload={"key": "val"}, tenant=tenant, db=mock_db)

    assert result["type"] == "export"
    assert result["status"] == "pending"
    mock_db.add.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_job_list():
    tenant = _make_tenant()
    mock_db = AsyncMock()

    jobs = [_make_job(tenant.id), _make_job(tenant.id, type="ai_completion")]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = jobs
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await job_list(tenant=tenant, db=mock_db)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_job_list_with_status_filter():
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await job_list(status="completed", tenant=tenant, db=mock_db)
    assert result == []


@pytest.mark.asyncio
async def test_job_list_invalid_status():
    tenant = _make_tenant()
    mock_db = AsyncMock()

    with pytest.raises(McpError, match="Invalid status"):
        await job_list(status="invalid", tenant=tenant, db=mock_db)


@pytest.mark.asyncio
async def test_job_get():
    tenant = _make_tenant()
    mock_db = AsyncMock()

    job = _make_job(tenant.id)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = job
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await job_get(str(job.id), tenant=tenant, db=mock_db)
    assert result["id"] == str(job.id)
    assert result["type"] == "export"


@pytest.mark.asyncio
async def test_job_get_not_found():
    tenant = _make_tenant()
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(McpError, match="not found"):
        await job_get(str(uuid.uuid4()), tenant=tenant, db=mock_db)


@pytest.mark.asyncio
async def test_job_cancel():
    tenant = _make_tenant()
    mock_db = AsyncMock()

    job = _make_job(tenant.id, status=JobStatus.PENDING)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = job
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await job_cancel(str(job.id), tenant=tenant, db=mock_db)
    assert result["status"] == "cancelled"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_job_cancel_completed():
    tenant = _make_tenant()
    mock_db = AsyncMock()

    job = _make_job(tenant.id, status=JobStatus.COMPLETED)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = job
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(McpError, match="Cannot cancel"):
        await job_cancel(str(job.id), tenant=tenant, db=mock_db)
