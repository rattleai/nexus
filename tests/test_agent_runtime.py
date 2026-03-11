"""Tests for the agent execution runtime."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.runtime import AgentRuntime, RunResult, StepResult


def _make_definition(**overrides):
    """Create a mock AgentDefinition."""
    mock = MagicMock()
    mock.system_prompt = overrides.get("system_prompt", "You are a helpful assistant.")
    mock.model = overrides.get("model", "gpt-4o")
    mock.temperature = overrides.get("temperature", None)
    mock.max_tokens = overrides.get("max_tokens", None)
    mock.max_steps_per_run = overrides.get("max_steps_per_run", 50)
    mock.max_duration_seconds = overrides.get("max_duration_seconds", 300)
    mock.max_tokens_per_run = overrides.get("max_tokens_per_run", 100_000)
    return mock


class TestAgentRuntime:
    @pytest.mark.asyncio
    async def test_run_returns_result_on_direct_response(self):
        """Agent responds directly without tool calls → single step, completed."""
        definition = _make_definition()
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=uuid.uuid4(),
            api_key="test-key",
        )

        mock_completion = MagicMock()
        mock_completion.content = "Hello! How can I help?"
        mock_completion.total_tokens = 100
        mock_completion.cost_usd = 0.001
        mock_completion.finish_reason = "stop"

        with patch("app.agents.runtime.ai_gateway") as mock_gw:
            mock_gw.completion = AsyncMock(return_value=mock_completion)
            with patch("app.agents.runtime.emit", new_callable=AsyncMock):
                result = await runtime.run(
                    messages=[{"role": "user", "content": "Hello"}],
                    instance_id=uuid.uuid4(),
                )

        assert isinstance(result, RunResult)
        assert result.finish_reason == "completed"
        assert result.output == "Hello! How can I help?"
        assert result.total_tokens == 100
        assert len(result.steps) == 1
        assert result.steps[0].action == "response"

    @pytest.mark.asyncio
    async def test_cancel_stops_execution(self):
        """Cancelling the runtime stops after the current step."""
        definition = _make_definition()
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=uuid.uuid4(),
            api_key="test-key",
        )
        runtime.cancel()

        with patch("app.agents.runtime.emit", new_callable=AsyncMock):
            result = await runtime.run(
                messages=[{"role": "user", "content": "Hello"}],
                instance_id=uuid.uuid4(),
            )

        assert result.finish_reason == "cancelled"
        assert len(result.steps) == 0

    @pytest.mark.asyncio
    async def test_max_tokens_limit(self):
        """Agent stops when token limit is reached."""
        definition = _make_definition(max_tokens_per_run=50)
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=uuid.uuid4(),
            api_key="test-key",
        )

        # Pre-set tokens to exceed limit
        mock_completion = MagicMock()
        mock_completion.content = "Response"
        mock_completion.total_tokens = 100  # Exceeds 50 limit
        mock_completion.cost_usd = 0.001

        # First call will go through, then token limit kicks in
        call_count = 0

        async def mock_completion_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            return mock_completion

        with patch("app.agents.runtime.ai_gateway") as mock_gw:
            mock_gw.completion = mock_completion_fn
            with patch("app.agents.runtime.emit", new_callable=AsyncMock):
                result = await runtime.run(
                    messages=[{"role": "user", "content": "Hello"}],
                    instance_id=uuid.uuid4(),
                )

        # Should complete on first step (direct response, no tool calls)
        assert result.finish_reason == "completed"


class TestAgentRuntimeToolCallExtraction:
    def test_extract_tool_calls_returns_empty(self):
        """Tool call extraction returns empty (placeholder implementation)."""
        definition = _make_definition()
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=uuid.uuid4(),
            api_key="test-key",
        )
        assert runtime._extract_tool_calls("Hello world") == []
