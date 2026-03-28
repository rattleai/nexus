"""Tests for session expiry edge cases in conversation_reply.

Verifies that:
    - Expired sessions (expires_at in the past) return 410
    - Idle sessions (last_activity_at + idle_timeout exceeded) return 410 and are marked EXPIRED
    - Sessions at max_turns boundary return 429
    - Completed sessions return 400
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.agents.models import SessionStatus


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
    session.expires_at = expires_at
    session.last_activity_at = last_activity_at
    session.definition_id = uuid.uuid4()
    session.messages = []
    session.total_tokens = 0
    session.total_cost_usd = 0.0
    return session


def _make_redis_with_rate_limit(count: int = 1):
    """Create a Redis mock that passes rate limiting with the given counter."""
    mock_redis = MagicMock()
    rate_pipe = MagicMock()
    rate_pipe.incr = MagicMock()
    rate_pipe.expire = MagicMock()
    rate_pipe.execute = AsyncMock(return_value=[count])
    mock_redis.pipeline.return_value = rate_pipe
    return mock_redis


# ── TestSessionExpiresAt ──────────────────────────────────────────────


class TestSessionExpiresAt:
    """Session with expires_at in the past should return 410 Gone."""

    @pytest.mark.asyncio
    async def test_expired_session_returns_410(self):
        """expires_at is 5 minutes in the past -> 410."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = _make_mock_session(
            tenant_id=tenant_id,
            session_id=session_id,
            status=SessionStatus.ACTIVE,
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
            last_activity_at=datetime.now(UTC) - timedelta(minutes=10),
        )

        mock_redis = _make_redis_with_rate_limit(1)

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        db.commit = AsyncMock()

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
            assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_session_just_expired_returns_410(self):
        """expires_at is 1 second in the past -> 410."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = _make_mock_session(
            tenant_id=tenant_id,
            session_id=session_id,
            status=SessionStatus.ACTIVE,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
            last_activity_at=datetime.now(UTC) - timedelta(minutes=1),
        )

        mock_redis = _make_redis_with_rate_limit(1)

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        db.commit = AsyncMock()

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


# ── TestSessionIdleTimeout ────────────────────────────────────────────


class TestSessionIdleTimeout:
    """Session whose last_activity_at + idle_timeout is exceeded -> 410 + status set to EXPIRED."""

    @pytest.mark.asyncio
    async def test_idle_session_returns_410(self):
        """last_activity_at is 2 hours ago, idle_timeout is 3600s -> expired."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = _make_mock_session(
            tenant_id=tenant_id,
            session_id=session_id,
            status=SessionStatus.ACTIVE,
            idle_timeout_seconds=3600,
            last_activity_at=datetime.now(UTC) - timedelta(hours=2),
            expires_at=datetime.now(UTC) + timedelta(hours=1),  # Not hard-expired
        )

        mock_redis = _make_redis_with_rate_limit(1)

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        db.commit = AsyncMock()

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
            assert "inactivity" in exc_info.value.detail.lower()
            # Session status should be updated to EXPIRED
            assert session.status == SessionStatus.EXPIRED
            db.commit.assert_awaited()


# ── TestSessionMaxTurns ───────────────────────────────────────────────


class TestSessionMaxTurns:
    """Session at max_turns boundary -> 429 Too Many Requests."""

    @pytest.mark.asyncio
    async def test_max_turns_reached_returns_429(self):
        """turn_count == AGENT_SESSION_MAX_TURNS -> 429."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = _make_mock_session(
            tenant_id=tenant_id,
            session_id=session_id,
            status=SessionStatus.ACTIVE,
            turn_count=50,  # Default max is 50
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_activity_at=datetime.now(UTC),
        )

        mock_redis = _make_redis_with_rate_limit(1)

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        db.commit = AsyncMock()

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.message = "hello"
        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.config.settings") as mock_settings,
        ):
            mock_settings.AGENT_SESSION_MAX_TURNS = 50

            with pytest.raises(HTTPException) as exc_info:
                await conversation_reply(
                    session_id=session_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )

            assert exc_info.value.status_code == 429
            assert "maximum number of turns" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_one_below_max_turns_passes_check(self):
        """turn_count == AGENT_SESSION_MAX_TURNS - 1 -> passes the turn check."""
        # This test verifies the boundary: only turn_count >= max is rejected
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = _make_mock_session(
            tenant_id=tenant_id,
            session_id=session_id,
            status=SessionStatus.ACTIVE,
            turn_count=49,  # One below the limit
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_activity_at=datetime.now(UTC),
        )

        mock_redis = MagicMock()
        lock = AsyncMock()
        lock.acquire = AsyncMock(return_value=True)
        lock.release = AsyncMock()
        mock_redis.lock.return_value = lock

        rate_pipe = MagicMock()
        rate_pipe.incr = MagicMock()
        rate_pipe.expire = MagicMock()
        rate_pipe.execute = AsyncMock(return_value=[1])
        mock_redis.pipeline.return_value = rate_pipe

        mock_agent = MagicMock()
        mock_agent.status = MagicMock()
        mock_agent.status.__eq__ = lambda self, other: True  # AgentStatus.ACTIVE
        mock_agent.max_concurrent_instances = 0  # No limit

        db = AsyncMock()
        db.get = AsyncMock(side_effect=[session, mock_agent])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()  # TOCTOU refresh
        db.add = MagicMock()

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.message = "hello"
        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.config.settings") as mock_settings,
        ):
            mock_settings.AGENT_SESSION_MAX_TURNS = 50
            mock_settings.AGENT_CONVERSATION_LOCK_TIMEOUT = 30
            mock_settings.AGENT_RATE_LIMIT_FAIL_OPEN = False

            # Will proceed past the turn check and fail later (e.g., no AI key).
            # The important assertion is that it does NOT raise 429.
            try:
                await conversation_reply(
                    session_id=session_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )
            except HTTPException as exc:
                # Any error other than 429 means the turn check passed
                assert exc.status_code != 429


# ── TestSessionStatusCompleted ────────────────────────────────────────


class TestSessionStatusCompleted:
    """Session with status COMPLETED -> 400 Bad Request."""

    @pytest.mark.asyncio
    async def test_completed_session_returns_400(self):
        """COMPLETED session cannot accept replies."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = _make_mock_session(
            tenant_id=tenant_id,
            session_id=session_id,
            status=SessionStatus.COMPLETED,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_activity_at=datetime.now(UTC),
        )

        mock_redis = _make_redis_with_rate_limit(1)

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)

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
            assert "completed" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_expired_session_status_returns_400(self):
        """Session with status=EXPIRED (already marked) returns 400."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        session = _make_mock_session(
            tenant_id=tenant_id,
            session_id=session_id,
            status=SessionStatus.EXPIRED,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_activity_at=datetime.now(UTC),
        )

        mock_redis = _make_redis_with_rate_limit(1)

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)

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
            assert "expired" in exc_info.value.detail.lower()
