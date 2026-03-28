"""Tests for rate limiting in conversation start and reply endpoints.

Verifies that:
    - Session creation rate limit: 429 on 11th call within the window
    - Reply rate limit: 429 on 21st call within the window
    - Redis unavailable for rate limit: 503 (fail-closed, not silent pass)
    - Rate limit counter expiry: pipeline calls EXPIRE with 60s TTL
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi import HTTPException

from app.agents.models import AgentStatus, SessionStatus


# ── Helpers ────────────────────────────────────────────────────────────


def _make_redis_pipeline(incr_result: int):
    """Create a Redis mock with pipeline returning given INCR result."""
    mock_redis = MagicMock()
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=[incr_result])
    mock_redis.pipeline.return_value = pipe
    return mock_redis, pipe


def _make_failing_redis_pipeline():
    """Create a Redis mock whose pipeline.execute raises ConnectionError."""
    mock_redis = MagicMock()
    pipe = MagicMock()
    pipe.incr = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(side_effect=ConnectionError("Redis down"))
    mock_redis.pipeline.return_value = pipe
    return mock_redis, pipe


def _make_mock_session(
    tenant_id: uuid.UUID,
    *,
    status: SessionStatus = SessionStatus.ACTIVE,
    turn_count: int = 0,
):
    """Create a minimal mock session for reply tests."""
    session = MagicMock()
    session.id = uuid.uuid4()
    session.tenant_id = tenant_id
    session.status = status
    session.is_interactive = True
    session.turn_count = turn_count
    session.idle_timeout_seconds = 3600
    session.expires_at = datetime.now(UTC) + timedelta(hours=1)
    session.last_activity_at = datetime.now(UTC)
    session.definition_id = uuid.uuid4()
    session.messages = []
    session.total_tokens = 0
    session.total_cost_usd = 0.0
    return session


def _make_mock_agent(tenant_id: uuid.UUID):
    """Create a minimal mock agent definition."""
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.tenant_id = tenant_id
    agent.name = "test-agent"
    agent.status = AgentStatus.ACTIVE
    agent.max_concurrent_instances = 0
    agent.deleted_at = None
    return agent


# ── TestSessionCreationRateLimit ──────────────────────────────────────


class TestSessionCreationRateLimit:
    """Max 10 session creations per minute per tenant."""

    @pytest.mark.asyncio
    async def test_11th_session_creation_returns_429(self):
        """INCR returns 11 -> over the 10/minute limit -> 429."""
        from app.api.v1.agents import start_conversation

        tenant_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        mock_redis, pipe = _make_redis_pipeline(incr_result=11)

        agent = _make_mock_agent(tenant_id)

        db = AsyncMock()
        db.get = AsyncMock(return_value=agent)
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.input_data = {"prompt": "hello"}
        mock_body.idle_timeout_seconds = None

        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            patch("app.api.v1.agents._get_agent_or_404", new_callable=AsyncMock, return_value=agent),
            patch("app.api.v1.agents._enforce_concurrent_limit", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            # The function imports redis_pool inside the body
            patch("app.api.v1.agents.emit", new_callable=AsyncMock),
            patch("app.billing.entitlements.entitlements") as mock_ent,
        ):
            mock_ent.require_feature = AsyncMock()

            with pytest.raises(HTTPException) as exc_info:
                await start_conversation(
                    agent_id=agent_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )

            assert exc_info.value.status_code == 429
            assert "rate limit" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_10th_session_creation_passes(self):
        """INCR returns 10 -> exactly at the limit -> allowed."""
        from app.api.v1.agents import start_conversation

        tenant_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        mock_redis, pipe = _make_redis_pipeline(incr_result=10)

        # Lock for later (conversation_reply uses lock, start_conversation doesn't)
        mock_redis.lock = MagicMock()

        agent = _make_mock_agent(tenant_id)

        db = AsyncMock()
        db.get = AsyncMock(return_value=agent)
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.input_data = {"prompt": "hello"}
        mock_body.idle_timeout_seconds = None

        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            patch("app.api.v1.agents._get_agent_or_404", new_callable=AsyncMock, return_value=agent),
            patch("app.api.v1.agents._enforce_concurrent_limit", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.api.v1.agents.emit", new_callable=AsyncMock),
            patch("app.billing.entitlements.entitlements") as mock_ent,
        ):
            mock_ent.require_feature = AsyncMock()

            # Should NOT raise 429 — it will proceed past rate limit
            # and may fail later (e.g., no API key), which is fine.
            try:
                await start_conversation(
                    agent_id=agent_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )
            except HTTPException as exc:
                assert exc.status_code != 429, "Should not hit rate limit at count=10"
            except Exception:
                # Non-HTTP errors mean we passed the rate limit check successfully
                pass


# ── TestReplyRateLimit ────────────────────────────────────────────────


class TestReplyRateLimit:
    """Max 20 replies per minute per session."""

    @pytest.mark.asyncio
    async def test_21st_reply_returns_429(self):
        """INCR returns 21 -> over the 20/minute limit -> 429."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        mock_redis, pipe = _make_redis_pipeline(incr_result=21)

        session = _make_mock_session(tenant_id)

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

            assert exc_info.value.status_code == 429
            assert "rate limit" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_20th_reply_passes(self):
        """INCR returns 20 -> exactly at the limit -> allowed."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        mock_redis, pipe = _make_redis_pipeline(incr_result=20)

        # Need lock for conversation_reply
        lock = AsyncMock()
        lock.acquire = AsyncMock(return_value=True)
        lock.release = AsyncMock()
        mock_redis.lock.return_value = lock

        session = _make_mock_session(tenant_id)
        agent = _make_mock_agent(tenant_id)

        # db.get is called first for session, then for agent definition after lock
        db = AsyncMock()
        db.get = AsyncMock(side_effect=[session, agent])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock()

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

            # Should NOT raise 429
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
                assert exc.status_code != 429, "Should not hit rate limit at count=20"
            except Exception:
                # Non-HTTP errors mean we passed the rate limit check successfully
                pass


# ── TestRedisUnavailableRateLimit ─────────────────────────────────────


class TestRedisUnavailableRateLimit:
    """Redis unavailable for rate limiting -> 503 (fail-closed)."""

    @pytest.mark.asyncio
    async def test_session_creation_redis_down_returns_503(self):
        """ConnectionError from pipeline.execute -> 503, not silent pass."""
        from app.api.v1.agents import start_conversation

        tenant_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        mock_redis, pipe = _make_failing_redis_pipeline()

        agent = _make_mock_agent(tenant_id)

        db = AsyncMock()
        db.get = AsyncMock(return_value=agent)
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.input_data = {"prompt": "hello"}
        mock_body.idle_timeout_seconds = None

        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            patch("app.api.v1.agents._get_agent_or_404", new_callable=AsyncMock, return_value=agent),
            patch("app.api.v1.agents._enforce_concurrent_limit", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.api.v1.agents.emit", new_callable=AsyncMock),
            patch("app.billing.entitlements.entitlements") as mock_ent,
            patch("app.config.settings") as mock_settings,
        ):
            mock_ent.require_feature = AsyncMock()
            mock_settings.AGENT_RATE_LIMIT_FAIL_OPEN = False

            with pytest.raises(HTTPException) as exc_info:
                await start_conversation(
                    agent_id=agent_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )

            assert exc_info.value.status_code == 503
            assert "unavailable" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_reply_redis_down_returns_503(self):
        """ConnectionError from pipeline.execute in reply -> 503."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        mock_redis, pipe = _make_failing_redis_pipeline()

        session = _make_mock_session(tenant_id)

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
            mock_settings.AGENT_RATE_LIMIT_FAIL_OPEN = False

            with pytest.raises(HTTPException) as exc_info:
                await conversation_reply(
                    session_id=session_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )

            assert exc_info.value.status_code == 503
            assert "unavailable" in exc_info.value.detail.lower()


# ── TestRateLimitCounterExpiry ────────────────────────────────────────


class TestRateLimitCounterExpiry:
    """Verify pipeline calls EXPIRE with 60s TTL."""

    @pytest.mark.asyncio
    async def test_session_creation_sets_60s_expiry(self):
        """Rate limit pipeline calls expire with 60-second TTL."""
        from app.api.v1.agents import start_conversation

        tenant_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        mock_redis, pipe = _make_redis_pipeline(incr_result=1)

        agent = _make_mock_agent(tenant_id)

        db = AsyncMock()
        db.get = AsyncMock(return_value=agent)
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.refresh = AsyncMock()

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_body = MagicMock()
        mock_body.input_data = {"prompt": "hello"}
        mock_body.idle_timeout_seconds = None

        mock_request = MagicMock()

        with (
            patch("app.api.v1.agents.set_tenant_context", new_callable=AsyncMock),
            patch("app.api.v1.agents._get_agent_or_404", new_callable=AsyncMock, return_value=agent),
            patch("app.api.v1.agents._enforce_concurrent_limit", new_callable=AsyncMock),
            patch("app.core.redis.redis_pool", mock_redis),
            patch("app.api.v1.agents.emit", new_callable=AsyncMock),
            patch("app.billing.entitlements.entitlements") as mock_ent,
        ):
            mock_ent.require_feature = AsyncMock()

            # Will proceed past rate limit — may error later, which is fine
            try:
                await start_conversation(
                    agent_id=agent_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )
            except Exception:
                pass  # We only care about the pipeline calls

            # Verify expire was called with 60-second TTL
            expire_calls = pipe.expire.call_args_list
            assert len(expire_calls) >= 1
            # The expire call should use the rate key and 60s TTL
            _, kwargs = expire_calls[0]
            args = expire_calls[0][0] if expire_calls[0][0] else ()
            # pipe.expire(key, 60) — second positional arg is 60
            assert args[1] == 60, f"Expected 60s TTL, got {args[1]}"

    @pytest.mark.asyncio
    async def test_reply_rate_limit_sets_60s_expiry(self):
        """Reply rate limit pipeline calls expire with 60-second TTL."""
        from app.api.v1.agents import conversation_reply

        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        mock_redis, pipe = _make_redis_pipeline(incr_result=1)

        # Lock mock for the reply path
        lock = AsyncMock()
        lock.acquire = AsyncMock(return_value=True)
        lock.release = AsyncMock()
        mock_redis.lock.return_value = lock

        session = _make_mock_session(tenant_id)

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
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

            try:
                await conversation_reply(
                    session_id=session_id,
                    body=mock_body,
                    request=mock_request,
                    tenant=mock_tenant,
                    api_key=None,
                    db=db,
                )
            except Exception:
                pass

            # Verify expire was called with 60s TTL
            expire_calls = pipe.expire.call_args_list
            assert len(expire_calls) >= 1
            args = expire_calls[0][0]
            assert args[1] == 60, f"Expected 60s TTL, got {args[1]}"
