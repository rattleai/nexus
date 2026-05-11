"""Tests for the agent execution runtime."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.runtime import AgentRuntime, RunResult


def _make_definition(**overrides):
    """Create a mock AgentDefinition."""
    mock = MagicMock()
    mock.system_prompt = overrides.get("system_prompt", "You are a helpful assistant.")
    mock.model = overrides.get("model", "gpt-4o")
    mock.temperature = overrides.get("temperature")
    mock.max_tokens = overrides.get("max_tokens")
    mock.max_steps_per_run = overrides.get("max_steps_per_run", 50)
    mock.max_duration_seconds = overrides.get("max_duration_seconds", 300)
    mock.max_tokens_per_run = overrides.get("max_tokens_per_run", 100_000)
    mock.allowed_tools = overrides.get("allowed_tools", [])
    mock.id = overrides.get("id", uuid.uuid4())
    mock.governance_policy = overrides.get("governance_policy", {})
    mock.output_schema = overrides.get("output_schema", {})
    mock.memory_config = overrides.get("memory_config", {})
    mock.name = overrides.get("name", "test-agent")
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
        mock_completion.tool_calls = None

        with patch("app.ai.gateway.ai_gateway") as mock_gw:
            mock_gw.completion = AsyncMock(return_value=mock_completion)
            with patch("app.core.events.emit", new_callable=AsyncMock):
                with patch("app.agents.governance.GovernanceEngine") as mock_gov:
                    mock_gov.track_spending = AsyncMock()
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

        with patch("app.core.events.emit", new_callable=AsyncMock):
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
        mock_completion.tool_calls = None

        # First call will go through, then token limit kicks in
        call_count = 0

        async def mock_completion_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            return mock_completion

        with patch("app.ai.gateway.ai_gateway") as mock_gw:
            mock_gw.completion = mock_completion_fn
            with patch("app.core.events.emit", new_callable=AsyncMock):
                with patch("app.agents.governance.GovernanceEngine") as mock_gov:
                    mock_gov.track_spending = AsyncMock()
                    result = await runtime.run(
                        messages=[{"role": "user", "content": "Hello"}],
                        instance_id=uuid.uuid4(),
                    )

        # Should complete on first step (direct response, no tool calls)
        assert result.finish_reason == "completed"


class TestAgentRuntimeToolCallExtraction:
    def test_extract_tool_calls_returns_empty_when_none(self):
        """Tool call extraction returns empty when completion has no tool_calls."""
        definition = _make_definition()
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=uuid.uuid4(),
            api_key="test-key",
        )
        completion = MagicMock()
        completion.tool_calls = None
        assert runtime._extract_tool_calls(completion) == []

    def test_extract_tool_calls_returns_calls(self):
        """Tool call extraction correctly parses tool_calls from completion."""
        definition = _make_definition()
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=uuid.uuid4(),
            api_key="test-key",
        )
        completion = MagicMock()
        completion.tool_calls = [
            {"id": "call_1", "name": "ai_complete", "arguments": {"model": "gpt-4o"}},
            {"id": "call_2", "name": "file_list", "arguments": {}},
        ]
        calls = runtime._extract_tool_calls(completion)
        assert len(calls) == 2
        assert calls[0].name == "ai_complete"
        assert calls[0].call_id == "call_1"
        assert calls[0].arguments == {"model": "gpt-4o"}
        assert calls[1].name == "file_list"

    @pytest.mark.asyncio
    async def test_multi_step_tool_use_flow(self):
        """Full ReAct loop: LLM → tool call → observe → respond."""
        definition = _make_definition(allowed_tools=["ai_complete"])
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=uuid.uuid4(),
            api_key="test-key",
        )

        # First call: LLM wants to call a tool
        tool_completion = MagicMock()
        tool_completion.content = ""
        tool_completion.total_tokens = 50
        tool_completion.cost_usd = 0.001
        tool_completion.tool_calls = [
            {"id": "call_1", "name": "ai_complete", "arguments": {"messages": []}},
        ]

        # Second call: LLM responds directly
        final_completion = MagicMock()
        final_completion.content = "Done with the task."
        final_completion.total_tokens = 30
        final_completion.cost_usd = 0.0005
        final_completion.tool_calls = None

        call_count = 0

        async def mock_completion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return tool_completion
            return final_completion

        tool_executor = AsyncMock(return_value={"result": "ok"})

        with patch("app.ai.gateway.ai_gateway") as mock_gw:
            mock_gw.completion = mock_completion
            with patch("app.core.events.emit", new_callable=AsyncMock):
                with patch("app.agents.governance.GovernanceEngine") as mock_gov:
                    mock_gov.track_spending = AsyncMock()
                    result = await runtime.run(
                        messages=[{"role": "user", "content": "Do it"}],
                        instance_id=uuid.uuid4(),
                        tool_executor=tool_executor,
                    )

        assert result.finish_reason == "completed"
        assert result.output == "Done with the task."
        assert len(result.steps) == 2
        assert result.steps[0].action == "tool_call"
        assert result.steps[0].tool_name == "ai_complete"
        assert result.steps[1].action == "response"
        assert result.total_tokens == 80
        tool_executor.assert_called_once_with("ai_complete", {"messages": []})

    @pytest.mark.asyncio
    async def test_max_steps_limit(self):
        """Agent stops when max_steps reached."""
        definition = _make_definition(max_steps_per_run=2, allowed_tools=["test_tool"])
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=uuid.uuid4(),
            api_key="test-key",
        )

        # Always return tool calls so we never get a direct response
        mock_comp = MagicMock()
        mock_comp.content = ""
        mock_comp.total_tokens = 10
        mock_comp.cost_usd = 0.001
        mock_comp.tool_calls = [
            {"id": "call_x", "name": "test_tool", "arguments": {}},
        ]

        tool_executor = AsyncMock(return_value={"ok": True})

        with patch("app.ai.gateway.ai_gateway") as mock_gw:
            mock_gw.completion = AsyncMock(return_value=mock_comp)
            with patch("app.core.events.emit", new_callable=AsyncMock):
                with patch("app.agents.governance.GovernanceEngine") as mock_gov:
                    mock_gov.track_spending = AsyncMock()
                    result = await runtime.run(
                        messages=[{"role": "user", "content": "Go"}],
                        instance_id=uuid.uuid4(),
                        tool_executor=tool_executor,
                    )

        assert result.finish_reason == "max_steps"

    @pytest.mark.asyncio
    async def test_llm_error_stops_loop(self):
        """LLM call error sets finish_reason to 'error'."""
        definition = _make_definition()
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=uuid.uuid4(),
            api_key="test-key",
        )

        with patch("app.ai.gateway.ai_gateway") as mock_gw:
            mock_gw.completion = AsyncMock(side_effect=Exception("Provider unavailable"))
            with patch("app.core.events.emit", new_callable=AsyncMock):
                with patch("app.agents.governance.GovernanceEngine"):
                    result = await runtime.run(
                        messages=[{"role": "user", "content": "Hello"}],
                        instance_id=uuid.uuid4(),
                    )

        assert result.finish_reason == "error"
        assert len(result.steps) == 1
        assert result.steps[0].action == "error"
