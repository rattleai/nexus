"""Tests for agent ReAct loop SSE streaming."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.runtime import AgentRuntime, RunResult, StepResult


@pytest.fixture
def mock_definition():
    """Create a mock agent definition."""
    defn = MagicMock()
    defn.id = uuid.uuid4()
    defn.name = "test-agent"
    defn.model = "gpt-4o"
    defn.system_prompt = "You are a test agent."
    defn.temperature = 0.7
    defn.max_tokens = 4096
    defn.max_steps_per_run = 10
    defn.max_tokens_per_run = 100000
    defn.max_duration_seconds = 300
    defn.allowed_tools = []
    defn.tool_versions = {}
    defn.memory_config = {}
    defn.governance_policy = {}
    defn.output_schema = None
    defn.parallel_tool_execution = True
    return defn


@pytest.fixture
def runtime(mock_definition):
    """Create a runtime instance."""
    return AgentRuntime(
        definition=mock_definition,
        tenant_id=uuid.uuid4(),
        api_key="test-key",
        key_source="platform",
    )


@pytest.mark.asyncio
async def test_run_stream_yields_events(runtime):
    """run_stream should yield SSE events including run_started and run_completed."""
    # Mock the AI gateway to return a simple response
    mock_completion = MagicMock()
    mock_completion.total_tokens = 100
    mock_completion.cost_usd = 0.001
    mock_completion.content = "Hello, I'm the agent!"
    mock_completion.tool_calls = None

    with patch("app.ai.gateway.ai_gateway") as mock_gw, \
         patch("app.agents.governance.GovernanceEngine") as mock_gov, \
         patch("app.agents.validation.validate_agent_output", return_value=(True, [], "Hello, I'm the agent!")):
        mock_gw.completion = AsyncMock(return_value=mock_completion)

        events = []
        async for event in runtime.run_stream(
            messages=[{"role": "user", "content": "Hello"}],
            instance_id=uuid.uuid4(),
        ):
            events.append(event)

    event_types = [e["event"] for e in events]
    assert "run_started" in event_types
    assert "run_completed" in event_types
    assert "step_started" in event_types


@pytest.mark.asyncio
async def test_run_stream_cancellation(runtime):
    """run_stream should stop when cancelled."""
    mock_completion = MagicMock()
    mock_completion.total_tokens = 100
    mock_completion.cost_usd = 0.001
    mock_completion.content = "Response"
    mock_completion.tool_calls = None

    # Cancel immediately
    runtime.cancel()

    events = []
    async for event in runtime.run_stream(
        messages=[{"role": "user", "content": "Hello"}],
        instance_id=uuid.uuid4(),
    ):
        events.append(event)

    event_types = [e["event"] for e in events]
    assert "run_started" in event_types
    assert "run_completed" in event_types
    # Check that cancellation was detected
    completed_event = next(e for e in events if e["event"] == "run_completed")
    assert completed_event["data"]["finish_reason"] == "cancelled"
