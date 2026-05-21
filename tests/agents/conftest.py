"""Shared fixtures and factory functions for the agent test suite."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.models import AgentStatus, InstanceStatus

# ── Factory Functions ─────────────────────────────────────────────────


def make_agent_definition(**overrides):
    """Create a MagicMock that mimics an AgentDefinition with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "name": "test-agent",
        "slug": "test-agent",
        "status": AgentStatus.ACTIVE,
        "system_prompt": "You are a helpful assistant.",
        "model": "gpt-4o",
        "temperature": 0.7,
        "max_tokens": 4096,
        "max_steps_per_run": 50,
        "max_duration_seconds": 300,
        "max_tokens_per_run": 100_000,
        "allowed_tools": [],
        "governance_policy": {},
        "sandbox_enabled": False,
        "memory_config": {},
        "deleted_at": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def make_agent_instance(**overrides):
    """Create a MagicMock that mimics an AgentInstance with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "definition_id": uuid.uuid4(),
        "status": InstanceStatus.PENDING,
        "steps_executed": 0,
        "tokens_used": 0,
        "cost_usd": 0.0,
        "input_data": {},
        "output_data": {},
        "error": None,
        "started_at": None,
        "completed_at": None,
        "idempotency_key": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def make_completion_response(**overrides):
    """Create a MagicMock that mimics an LLM completion response."""
    defaults = {
        "content": "This is a test response.",
        "total_tokens": 150,
        "cost_usd": 0.002,
        "finish_reason": "stop",
        "tool_calls": None,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


# ── Shared Fixtures ───────────────────────────────────────────────────


@pytest.fixture()
def mock_redis_pool():
    """Patch redis_pool in all agent modules that import it."""
    redis = AsyncMock()
    with (
        patch("app.agents.memory.redis_pool", redis),
        patch("app.agents.governance.redis_pool", redis),
        patch("app.agents.a2a.redis_pool", redis),
        patch("app.agents.db_gateway.redis_pool", redis),
        patch("app.agents.threat_detection.redis_pool", redis),
        patch("app.agents.a2a_security.redis_pool", redis),
    ):
        yield redis


def make_mock_db():
    """Create an AsyncMock for AsyncSession with sync methods properly mocked.

    SQLAlchemy's AsyncSession.add() is synchronous — using AsyncMock would
    return an unawaited coroutine and trigger RuntimeWarnings in tests.
    """
    session = AsyncMock()
    session.add = MagicMock()  # add() is sync on AsyncSession
    return session


@pytest.fixture()
def mock_db_session():
    """Return an AsyncMock standing in for an AsyncSession."""
    return make_mock_db()


@pytest.fixture()
def mock_emit():
    """Patch the domain-event emit function."""
    with patch("app.core.events.emit", new_callable=AsyncMock) as emitter:
        yield emitter
