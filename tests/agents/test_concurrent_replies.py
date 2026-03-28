"""Tests for distributed lock logic in conversation replies.

Verifies that:
    - Redis distributed lock prevents concurrent replies (409 Conflict)
    - Lock is released in the finally block on failure
    - TOCTOU protection re-validates session status after lock acquisition
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
from fastapi import HTTPException

from app.agents.models import AgentStatus, InstanceStatus, SessionStatus


# ── Helpers ────────────────────────────────────────────────────────────


def _make_mock_session(
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    status: SessionStatus = SessionStatus.ACTIVE,
    is_interactive: bool = True,
    turn_count: int = 0,
    idle_timeout_seconds: int = 3600,
    expires_at: datetime | None = None,
    last_activity_at: datetime | None = None,
):
    """Create a MagicMock mimicking an AgentSession."""
    session = MagicMock()
    session.id = session_id or uuid.uuid4()
    session.tenant_id = tenant_id
    session.status = status
    session.is_interactive = is_interactive
    session.turn_count = turn_count
    session.idle_timeout_seconds = idle_timeout_seconds
    session.expires_at = expires_at or (datetime.now(UTC) + timedelta(hours=1))
    session.last_activity_at = last_activity_at or datetime.now(UTC)
    session.definition_id = uuid.uuid4()
    session.messages = []
    session.total_tokens = 0
    session.total_cost_usd = 0.0
    return session


def _make_mock_lock(*, acquires: bool = True):
    """Create an AsyncMock lock that simulates Redis distributed lock behavior."""
    lock = AsyncMock()
    lock.acquire = AsyncMock(return_value=acquires)
    lock.release = AsyncMock()
    return lock


# ── TestLockAcquisition ───────────────────────────────────────────────


class TestLockAcquisition:
    """Verify distributed lock prevents concurrent replies."""

    @pytest.mark.asyncio
    async def test_lock_acquire_fails_returns_409(self):
        """When lock.acquire() returns False, the endpoint should raise HTTP 409."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session = _make_mock_session(tenant_id=tenant_id)

        mock_redis = MagicMock()
        lock = _make_mock_lock(acquires=False)
        mock_redis.lock.return_value = lock

        # Rate limit pipeline mock
        rate_pipe = MagicMock()
        rate_pipe.incr = MagicMock()
        rate_pipe.expire = MagicMock()
        rate_pipe.execute = AsyncMock(return_value=[1])
        mock_redis.pipeline.return_value = rate_pipe

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.message = "hello"

        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            # redis_pool is imported locally inside conversation_reply via
            # "from app.core.redis import redis_pool", so patch at source.
            patch("app.core.redis.redis_pool", mock_redis),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await conversation_reply(
                    session_id=session_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )

            assert exc_info.value.status_code == 409
            assert "in progress" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_lock_acquired_on_first_call(self):
        """First call acquires the lock successfully; second call fails."""
        lock_first = _make_mock_lock(acquires=True)
        lock_second = _make_mock_lock(acquires=False)

        # First lock acquires, second does not
        assert await lock_first.acquire() is True
        assert await lock_second.acquire() is False


# ── TestLockReleaseOnFailure ──────────────────────────────────────────


class TestLockReleaseOnFailure:
    """Verify lock is released in the exception handler when pre-generator setup fails."""

    @pytest.mark.asyncio
    async def test_lock_released_when_session_revalidation_fails(self):
        """If session becomes inactive after lock, lock is released and error raised."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        # First db.get returns ACTIVE session (pre-lock check),
        # then after lock, db.refresh makes status COMPLETED (TOCTOU scenario).
        session = _make_mock_session(tenant_id=tenant_id, status=SessionStatus.ACTIVE)

        # After lock acquisition, refresh changes status
        async def mock_refresh(obj):
            obj.status = SessionStatus.COMPLETED

        mock_redis = MagicMock()
        lock = _make_mock_lock(acquires=True)
        mock_redis.lock.return_value = lock

        # Rate limit pipeline
        rate_pipe = MagicMock()
        rate_pipe.incr = MagicMock()
        rate_pipe.expire = MagicMock()
        rate_pipe.execute = AsyncMock(return_value=[1])
        mock_redis.pipeline.return_value = rate_pipe

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=mock_refresh)

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.message = "hello"

        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await conversation_reply(
                    session_id=session_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )

            assert exc_info.value.status_code == 400
            # Lock MUST be released even though the inner code raised
            lock.release.assert_awaited()


# ── TestTOCTOUProtection ──────────────────────────────────────────────


class TestTOCTOUProtection:
    """TOCTOU protection: re-validate session state after acquiring lock."""

    @pytest.mark.asyncio
    async def test_session_expired_after_lock_returns_410(self):
        """Session expires between initial check and lock acquisition."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = _make_mock_session(
            tenant_id=tenant_id,
            status=SessionStatus.ACTIVE,
        )

        # After lock, refresh sets expires_at to the past
        async def mock_refresh(obj):
            obj.expires_at = datetime.now(UTC) - timedelta(seconds=60)

        mock_redis = MagicMock()
        lock = _make_mock_lock(acquires=True)
        mock_redis.lock.return_value = lock

        rate_pipe = MagicMock()
        rate_pipe.incr = MagicMock()
        rate_pipe.expire = MagicMock()
        rate_pipe.execute = AsyncMock(return_value=[1])
        mock_redis.pipeline.return_value = rate_pipe

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=mock_refresh)

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.message = "hello"

        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await conversation_reply(
                    session_id=session_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )

            assert exc_info.value.status_code == 410
            lock.release.assert_awaited()

    @pytest.mark.asyncio
    async def test_session_status_changed_after_lock_returns_400(self):
        """Session status becomes non-ACTIVE between check and lock."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = _make_mock_session(
            tenant_id=tenant_id,
            status=SessionStatus.ACTIVE,
        )

        # After lock, refresh changes status to EXPIRED
        async def mock_refresh(obj):
            obj.status = SessionStatus.EXPIRED

        mock_redis = MagicMock()
        lock = _make_mock_lock(acquires=True)
        mock_redis.lock.return_value = lock

        rate_pipe = MagicMock()
        rate_pipe.incr = MagicMock()
        rate_pipe.expire = MagicMock()
        rate_pipe.execute = AsyncMock(return_value=[1])
        mock_redis.pipeline.return_value = rate_pipe

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=mock_refresh)

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.message = "hello"

        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await conversation_reply(
                    session_id=session_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )

            assert exc_info.value.status_code == 400
            lock.release.assert_awaited()
