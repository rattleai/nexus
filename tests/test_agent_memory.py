"""Tests for the agent memory system."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.memory import AgentMemoryManager, _cosine_similarity


class TestShortTermMemory:
    @pytest.mark.asyncio
    async def test_set_and_get(self):
        mock_db = MagicMock()
        manager = AgentMemoryManager(mock_db)

        instance_id = uuid.uuid4()
        session_id = uuid.uuid4()

        with patch("app.agents.memory.redis_pool") as mock_redis:
            mock_redis.hset = AsyncMock()
            mock_redis.expire = AsyncMock()
            mock_redis.hget = AsyncMock(return_value=json.dumps({"key": "value"}))

            await manager.set_short_term(
                instance_id, session_id, "test_key", {"key": "value"},
            )
            mock_redis.hset.assert_called_once()
            mock_redis.expire.assert_called_once()

            result = await manager.get_short_term(instance_id, session_id, "test_key")
            assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self):
        mock_db = MagicMock()
        manager = AgentMemoryManager(mock_db)

        with patch("app.agents.memory.redis_pool") as mock_redis:
            mock_redis.hget = AsyncMock(return_value=None)

            result = await manager.get_short_term(
                uuid.uuid4(), uuid.uuid4(), "missing",
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_get_all_returns_dict(self):
        mock_db = MagicMock()
        manager = AgentMemoryManager(mock_db)

        with patch("app.agents.memory.redis_pool") as mock_redis:
            mock_redis.hgetall = AsyncMock(return_value={
                "k1": json.dumps("v1"),
                "k2": json.dumps(42),
            })

            result = await manager.get_all_short_term(uuid.uuid4(), uuid.uuid4())
            assert result == {"k1": "v1", "k2": 42}

    @pytest.mark.asyncio
    async def test_clear_deletes_key(self):
        mock_db = MagicMock()
        manager = AgentMemoryManager(mock_db)

        with patch("app.agents.memory.redis_pool") as mock_redis:
            mock_redis.delete = AsyncMock()

            await manager.clear_short_term(uuid.uuid4(), uuid.uuid4())
            mock_redis.delete.assert_called_once()


class TestSharedMemory:
    @pytest.mark.asyncio
    async def test_set_and_get_shared(self):
        mock_db = MagicMock()
        manager = AgentMemoryManager(mock_db)

        tenant_id = uuid.uuid4()
        workflow_id = uuid.uuid4()

        with patch("app.agents.memory.redis_pool") as mock_redis:
            mock_redis.hset = AsyncMock()
            mock_redis.expire = AsyncMock()
            mock_redis.hget = AsyncMock(return_value=json.dumps({"shared": True}))

            await manager.set_shared(tenant_id, workflow_id, "state", {"shared": True})
            result = await manager.get_shared(tenant_id, workflow_id, "state")
            assert result == {"shared": True}


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert _cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert _cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        assert _cosine_similarity([0, 0], [1, 1]) == pytest.approx(0.0)
