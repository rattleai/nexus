"""Tests for periodic Celery tasks."""

import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Ensure the tasks module can be imported without a real database by mocking
# create_engine at import time.  The _SyncSession created at module level in
# app.workers.tasks will be a MagicMock, which periodic.py re-exports.
_mock_engine = MagicMock()
_mock_session_cls = MagicMock()

with patch("sqlalchemy.create_engine", return_value=_mock_engine), \
     patch("sqlalchemy.orm.sessionmaker", return_value=_mock_session_cls):
    # Drop cached modules so they get re-imported with the patches active
    sys.modules.pop("app.workers.tasks", None)
    sys.modules.pop("app.workers.periodic", None)
    import app.workers.periodic
    import app.workers.tasks  # noqa: F401 — imported for side-effect


@pytest.fixture
def mock_sync_session():
    """Mock the sync session used by periodic tasks."""
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=session)
    ctx.__exit__ = MagicMock(return_value=False)
    with patch("app.workers.periodic._SyncSession", return_value=ctx):
        yield session


class TestCleanupExpiredJobs:
    def test_deletes_old_soft_deleted_jobs(self, mock_sync_session):
        from app.workers.periodic import cleanup_expired_jobs

        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_sync_session.execute.return_value = mock_result

        result = cleanup_expired_jobs()

        assert result["deleted"] == 5
        mock_sync_session.commit.assert_called_once()

    def test_handles_zero_deletions(self, mock_sync_session):
        from app.workers.periodic import cleanup_expired_jobs

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_sync_session.execute.return_value = mock_result

        result = cleanup_expired_jobs()

        assert result["deleted"] == 0


class TestCleanupStaleProcessing:
    def test_fails_stuck_jobs(self, mock_sync_session):
        from app.workers.periodic import cleanup_stale_processing

        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_sync_session.execute.return_value = mock_result

        result = cleanup_stale_processing()

        assert result["failed"] == 3
        mock_sync_session.commit.assert_called_once()

    def test_no_stuck_jobs(self, mock_sync_session):
        from app.workers.periodic import cleanup_stale_processing

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_sync_session.execute.return_value = mock_result

        result = cleanup_stale_processing()

        assert result["failed"] == 0


class TestCacheWarmup:
    def test_warms_active_tenants(self, mock_sync_session):
        from app.workers.periodic import cache_warmup

        tenant_mock = MagicMock()
        tenant_mock.id = uuid.uuid4()
        tenant_mock.name = "Test"
        tenant_mock.slug = "test"
        tenant_mock.plan = "free"
        tenant_mock.is_active = True

        scalars = MagicMock()
        scalars.all.return_value = [tenant_mock]
        exec_result = MagicMock()
        exec_result.scalars.return_value = scalars
        mock_sync_session.execute.return_value = exec_result

        mock_redis = MagicMock()
        mock_redis_module = MagicMock()
        mock_redis_module.from_url.return_value = mock_redis
        with patch.dict("sys.modules", {"redis": mock_redis_module}):
            result = cache_warmup()

        assert result["warmed"] == 1
        mock_redis.setex.assert_called_once()
        mock_redis.close.assert_called_once()


class TestStorageUsageReport:
    def test_reports_per_tenant(self, mock_sync_session):
        from app.workers.periodic import storage_usage_report

        tid = uuid.uuid4()
        mock_sync_session.execute.return_value.all.return_value = [
            (tid, "acme", "pro", 42),
        ]

        result = storage_usage_report()

        assert result["tenants"] == 1
        assert result["report"][0]["job_count"] == 42
        assert result["report"][0]["slug"] == "acme"
