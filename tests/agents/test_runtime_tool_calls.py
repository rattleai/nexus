"""Comprehensive tests for the agent runtime's tool execution pipeline.

Covers: tool call extraction, schema building, the full ReAct loop,
spending tracking, governance violations, and error handling.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.runtime import AgentRuntime, RunResult, ToolCall

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_definition(**overrides) -> MagicMock:
    """Build a mock AgentDefinition with sensible defaults."""
    defn = MagicMock()
    defn.id = overrides.get("id", uuid.uuid4())
    defn.system_prompt = overrides.get("system_prompt", "You are a helpful agent.")
    defn.model = overrides.get("model", "gpt-4o")
    defn.temperature = overrides.get("temperature", 0.7)
    defn.max_tokens = overrides.get("max_tokens", 4096)
    defn.max_steps_per_run = overrides.get("max_steps_per_run", 10)
    defn.max_tokens_per_run = overrides.get("max_tokens_per_run", 100_000)
    defn.max_duration_seconds = overrides.get("max_duration_seconds", 300)
    defn.allowed_tools = overrides.get("allowed_tools", ["ai_complete"])
    defn.governance_policy = overrides.get("governance_policy", {})
    defn.output_schema = overrides.get("output_schema", {})
    defn.memory_config = overrides.get("memory_config", {})
    defn.name = overrides.get("name", "test-agent")
    return defn


@dataclass
class FakeCompletionResult:
    """Lightweight stand-in for AICompletionResult."""

    id: str = "cmpl-1"
    model: str = "gpt-4o"
    provider: str = "openai"
    content: str = ""
    prompt_tokens: int = 10
    completion_tokens: int = 20
    total_tokens: int = 30
    cost_usd: float = 0.001
    billed_amount_usd: Decimal = Decimal("0.001")
    latency_ms: int = 100
    key_source: str = "platform"
    finish_reason: str | None = "stop"
    tool_calls: list[dict] | None = None


TENANT_ID = uuid.uuid4()
INSTANCE_ID = uuid.uuid4()
API_KEY = "sk-test-key"


def _build_runtime(**definition_overrides) -> AgentRuntime:
    return AgentRuntime(
        definition=_make_definition(**definition_overrides),
        tenant_id=TENANT_ID,
        api_key=API_KEY,
        key_source="platform",
    )


# Patch targets: ai_gateway and GovernanceEngine are imported locally inside
# AgentRuntime.run(), so we patch them at their defining modules.
_PATCH_AI_GW = "app.ai.gateway.ai_gateway"
_PATCH_GOVERNANCE = "app.agents.governance.GovernanceEngine"
_PATCH_EMIT = "app.agents.runtime.emit"
_PATCH_TOOL_REGISTRY = "app.agents.tool_registry.tool_registry"


# ===================================================================
# _extract_tool_calls
# ===================================================================


class TestExtractToolCalls:
    """Tests for AgentRuntime._extract_tool_calls."""

    def test_extracts_tool_calls_from_completion(self):
        runtime = _build_runtime()
        completion = FakeCompletionResult(
            tool_calls=[
                {"id": "call_1", "name": "ai_complete", "arguments": {"messages": []}},
                {"id": "call_2", "name": "file_upload", "arguments": {"filename": "a.txt", "content": "data"}},
            ],
        )

        result = runtime._extract_tool_calls(completion)

        assert len(result) == 2
        assert isinstance(result[0], ToolCall)
        assert result[0].name == "ai_complete"
        assert result[0].arguments == {"messages": []}
        assert result[0].call_id == "call_1"
        assert result[1].name == "file_upload"
        assert result[1].call_id == "call_2"

    def test_returns_empty_list_when_tool_calls_is_none(self):
        runtime = _build_runtime()
        completion = FakeCompletionResult(tool_calls=None)

        result = runtime._extract_tool_calls(completion)

        assert result == []

    def test_returns_empty_list_when_tool_calls_is_empty(self):
        runtime = _build_runtime()
        completion = FakeCompletionResult(tool_calls=[])

        result = runtime._extract_tool_calls(completion)

        assert result == []

    def test_missing_id_defaults_to_empty_string(self):
        runtime = _build_runtime()
        completion = FakeCompletionResult(
            tool_calls=[{"name": "ai_complete", "arguments": {}}],
        )

        result = runtime._extract_tool_calls(completion)

        assert len(result) == 1
        assert result[0].call_id == ""

    def test_missing_arguments_defaults_to_empty_dict(self):
        runtime = _build_runtime()
        completion = FakeCompletionResult(
            tool_calls=[{"id": "call_x", "name": "ai_complete"}],
        )

        result = runtime._extract_tool_calls(completion)

        assert result[0].arguments == {}


# ===================================================================
# _build_tools_schema
# ===================================================================


class TestBuildToolsSchema:
    """Tests for AgentRuntime._build_tools_schema."""

    def test_returns_openai_function_format_for_builtin_tools(self):
        runtime = _build_runtime(allowed_tools=["ai_complete"])

        with patch(_PATCH_TOOL_REGISTRY) as mock_registry:
            mock_registry.list_builtin_tools.return_value = {
                "ai_complete": {
                    "description": "Run an AI completion",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "messages": {"type": "array"},
                        },
                        "required": ["messages"],
                    },
                },
            }
            schema = runtime._build_tools_schema()

        assert schema is not None
        assert len(schema) == 1
        assert schema[0]["type"] == "function"
        assert schema[0]["function"]["name"] == "ai_complete"
        assert schema[0]["function"]["description"] == "Run an AI completion"
        assert "properties" in schema[0]["function"]["parameters"]

    def test_returns_none_when_no_allowed_tools(self):
        runtime = _build_runtime(allowed_tools=[])
        schema = runtime._build_tools_schema()
        assert schema is None

    def test_returns_none_when_allowed_tools_is_none(self):
        runtime = _build_runtime(allowed_tools=None)
        schema = runtime._build_tools_schema()
        assert schema is None

    def test_custom_tool_gets_generic_schema(self):
        runtime = _build_runtime(allowed_tools=["my_custom_tool"])

        with patch(_PATCH_TOOL_REGISTRY) as mock_registry:
            mock_registry.list_builtin_tools.return_value = {}
            schema = runtime._build_tools_schema()

        assert schema is not None
        assert len(schema) == 1
        assert schema[0]["function"]["name"] == "my_custom_tool"
        assert "Custom tool" in schema[0]["function"]["description"]

    def test_mixed_builtin_and_custom_tools(self):
        runtime = _build_runtime(allowed_tools=["ai_complete", "my_custom_tool"])

        with patch(_PATCH_TOOL_REGISTRY) as mock_registry:
            mock_registry.list_builtin_tools.return_value = {
                "ai_complete": {
                    "description": "Run an AI completion",
                    "input_schema": {
                        "type": "object",
                        "properties": {"messages": {"type": "array"}},
                        "required": ["messages"],
                    },
                },
            }
            schema = runtime._build_tools_schema()

        assert schema is not None
        assert len(schema) == 2
        names = [s["function"]["name"] for s in schema]
        assert "ai_complete" in names
        assert "my_custom_tool" in names


# ===================================================================
# Full ReAct loop
# ===================================================================


class TestReActLoop:
    """Tests for AgentRuntime.run -- the full ReAct loop."""

    @pytest.mark.asyncio
    async def test_tool_call_then_final_response(self):
        """LLM returns tool_call on step 1, then a final response on step 2."""
        runtime = _build_runtime()

        tool_call_completion = FakeCompletionResult(
            content="",
            total_tokens=30,
            cost_usd=0.001,
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "ai_complete",
                    "arguments": {"messages": [{"role": "user", "content": "hi"}]},
                },
            ],
        )
        final_completion = FakeCompletionResult(
            content="Done!",
            total_tokens=20,
            cost_usd=0.0005,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(side_effect=[tool_call_completion, final_completion])

        tool_executor = AsyncMock(return_value={"result": "tool output"})
        governance_checker = AsyncMock()

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {
                "ai_complete": {
                    "description": "Run an AI completion",
                    "input_schema": {"type": "object", "properties": {"messages": {"type": "array"}}},
                },
            }

            result = await runtime.run(
                messages=[{"role": "user", "content": "Hello"}],
                instance_id=INSTANCE_ID,
                tool_executor=tool_executor,
                governance_checker=governance_checker,
                db=None,
            )

        assert isinstance(result, RunResult)
        assert result.output == "Done!"
        assert result.finish_reason == "completed"
        assert len(result.steps) == 2
        assert result.steps[0].action == "tool_call"
        assert result.steps[0].tool_name == "ai_complete"
        assert result.steps[0].tool_result == {"result": "tool output"}
        assert result.steps[1].action == "response"
        assert result.steps[1].content == "Done!"
        assert result.total_tokens == 50  # 30 + 20
        assert result.total_cost_usd == pytest.approx(0.0015)

        # Tool executor was called with correct arguments
        tool_executor.assert_awaited_once_with(
            "ai_complete",
            {"messages": [{"role": "user", "content": "hi"}]},
        )

        # Governance checker was called before tool execution
        governance_checker.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_spending_tracked_after_each_llm_step(self):
        """GovernanceEngine.track_spending is called after every LLM call."""
        runtime = _build_runtime()

        # Two LLM calls: one with tool, one final
        call1 = FakeCompletionResult(
            total_tokens=30,
            cost_usd=0.001,
            tool_calls=[{"id": "call_1", "name": "ai_complete", "arguments": {}}],
        )
        call2 = FakeCompletionResult(
            content="final",
            total_tokens=20,
            cost_usd=0.0005,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(side_effect=[call1, call2])

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            await runtime.run(
                messages=[{"role": "user", "content": "go"}],
                instance_id=INSTANCE_ID,
                tool_executor=AsyncMock(return_value="ok"),
                db=None,
            )

            assert mock_gov.track_spending.await_count == 2
            # Verify the first call included the cost from step 1
            first_call_kwargs = mock_gov.track_spending.call_args_list[0].kwargs
            assert first_call_kwargs["cost_usd"] == 0.001
            assert first_call_kwargs["tenant_id"] == TENANT_ID

    @pytest.mark.asyncio
    async def test_governance_violation_stops_loop(self):
        """When governance_checker raises, the loop terminates with 'error' finish_reason."""
        runtime = _build_runtime()

        completion_with_tool = FakeCompletionResult(
            tool_calls=[{"id": "call_1", "name": "ai_complete", "arguments": {}}],
            total_tokens=30,
            cost_usd=0.001,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(return_value=completion_with_tool)

        governance_checker = AsyncMock(side_effect=RuntimeError("Policy violation: spending limit exceeded"))

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            result = await runtime.run(
                messages=[{"role": "user", "content": "do something"}],
                instance_id=INSTANCE_ID,
                tool_executor=AsyncMock(),
                governance_checker=governance_checker,
                db=None,
            )

        assert result.finish_reason == "error"
        # The tool executor should NOT have been called
        # (governance check happens before tool execution)

    @pytest.mark.asyncio
    async def test_tool_executor_error_returns_error_dict(self):
        """When tool_executor raises, the exception is caught and loop stops gracefully."""
        runtime = _build_runtime()

        completion_with_tool = FakeCompletionResult(
            tool_calls=[{"id": "call_1", "name": "ai_complete", "arguments": {}}],
            total_tokens=30,
            cost_usd=0.001,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(return_value=completion_with_tool)

        tool_executor = AsyncMock(side_effect=Exception("Connection refused"))

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            result = await runtime.run(
                messages=[{"role": "user", "content": "test"}],
                instance_id=INSTANCE_ID,
                tool_executor=tool_executor,
                governance_checker=None,
                db=None,
            )

        # The broad except in the loop catches the error
        assert result.finish_reason == "error"

    @pytest.mark.asyncio
    async def test_conversation_includes_tool_role_messages(self):
        """Verify 'tool' role messages with tool_call_id are appended to the conversation."""
        runtime = _build_runtime()

        tool_call_completion = FakeCompletionResult(
            content="",
            total_tokens=30,
            cost_usd=0.001,
            tool_calls=[
                {"id": "call_42", "name": "ai_complete", "arguments": {"messages": []}},
            ],
        )
        final_completion = FakeCompletionResult(
            content="All done",
            total_tokens=20,
            cost_usd=0.0005,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(side_effect=[tool_call_completion, final_completion])

        tool_executor = AsyncMock(return_value="tool result text")

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            await runtime.run(
                messages=[{"role": "user", "content": "test"}],
                instance_id=INSTANCE_ID,
                tool_executor=tool_executor,
                governance_checker=None,
                db=None,
            )

        # The second LLM call should have the tool role message in its conversation
        assert mock_ai_gw.completion.await_count == 2
        second_call_kwargs = mock_ai_gw.completion.call_args_list[1].kwargs
        messages = second_call_kwargs["messages"]

        # Find the tool role message
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["tool_call_id"] == "call_42"
        assert tool_messages[0]["content"] == "tool result text"

        # Also verify there is an assistant message with tool_calls before the tool message
        assistant_messages = [m for m in messages if m.get("role") == "assistant"]
        assert len(assistant_messages) >= 1
        # The assistant message should contain the tool_calls structure
        assistant_with_tc = [m for m in assistant_messages if "tool_calls" in m]
        assert len(assistant_with_tc) == 1
        assert assistant_with_tc[0]["tool_calls"][0]["id"] == "call_42"
        assert assistant_with_tc[0]["tool_calls"][0]["type"] == "function"
        assert assistant_with_tc[0]["tool_calls"][0]["function"]["name"] == "ai_complete"

    @pytest.mark.asyncio
    async def test_direct_response_without_tool_calls(self):
        """When LLM responds without tool_calls, return immediately."""
        runtime = _build_runtime()

        completion = FakeCompletionResult(
            content="Here is the answer.",
            total_tokens=25,
            cost_usd=0.0008,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(return_value=completion)

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            result = await runtime.run(
                messages=[{"role": "user", "content": "What is 2+2?"}],
                instance_id=INSTANCE_ID,
                tool_executor=AsyncMock(),
                db=None,
            )

        assert result.output == "Here is the answer."
        assert result.finish_reason == "completed"
        assert len(result.steps) == 1
        assert result.steps[0].action == "response"
        # LLM was only called once
        assert mock_ai_gw.completion.await_count == 1

    @pytest.mark.asyncio
    async def test_max_steps_reached(self):
        """When every LLM call returns a tool_call, the loop stops at max_steps."""
        runtime = _build_runtime(max_steps_per_run=3)

        perpetual_tool_call = FakeCompletionResult(
            total_tokens=10,
            cost_usd=0.0001,
            tool_calls=[{"id": "call_n", "name": "ai_complete", "arguments": {}}],
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(return_value=perpetual_tool_call)

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            result = await runtime.run(
                messages=[{"role": "user", "content": "loop forever"}],
                instance_id=INSTANCE_ID,
                tool_executor=AsyncMock(return_value="ok"),
                db=None,
            )

        assert result.finish_reason == "max_steps"
        assert len(result.steps) == 3
        assert mock_ai_gw.completion.await_count == 3

    @pytest.mark.asyncio
    async def test_cancellation_stops_loop(self):
        """Calling cancel() causes the loop to exit with 'cancelled' reason."""
        runtime = _build_runtime()
        runtime.cancel()  # Pre-cancel

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock()

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY),
        ):
            mock_gov.track_spending = AsyncMock()

            result = await runtime.run(
                messages=[{"role": "user", "content": "test"}],
                instance_id=INSTANCE_ID,
                tool_executor=AsyncMock(),
                db=None,
            )

        assert result.finish_reason == "cancelled"
        assert len(result.steps) == 0
        # LLM should never have been called
        mock_ai_gw.completion.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_system_prompt_prepended_to_conversation(self):
        """The agent's system_prompt should be prepended to the conversation."""
        runtime = _build_runtime(system_prompt="You are a test agent.")

        completion = FakeCompletionResult(
            content="ok",
            total_tokens=10,
            cost_usd=0.0001,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(return_value=completion)

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            await runtime.run(
                messages=[{"role": "user", "content": "hi"}],
                instance_id=INSTANCE_ID,
                tool_executor=None,
                db=None,
            )

        call_kwargs = mock_ai_gw.completion.call_args_list[0].kwargs
        messages = call_kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "You are a test agent."}
        assert messages[1] == {"role": "user", "content": "hi"}

    @pytest.mark.asyncio
    async def test_no_system_prompt_when_empty(self):
        """When system_prompt is empty, no system message is prepended."""
        runtime = _build_runtime(system_prompt="")

        completion = FakeCompletionResult(
            content="ok",
            total_tokens=10,
            cost_usd=0.0001,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(return_value=completion)

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            await runtime.run(
                messages=[{"role": "user", "content": "hi"}],
                instance_id=INSTANCE_ID,
                tool_executor=None,
                db=None,
            )

        call_kwargs = mock_ai_gw.completion.call_args_list[0].kwargs
        messages = call_kwargs["messages"]
        # Should start directly with the user message
        assert messages[0] == {"role": "user", "content": "hi"}

    @pytest.mark.asyncio
    async def test_tool_output_truncation(self):
        """Tool output longer than 20000 chars is truncated in the conversation."""
        runtime = _build_runtime()

        tool_call_completion = FakeCompletionResult(
            total_tokens=30,
            cost_usd=0.001,
            tool_calls=[{"id": "call_1", "name": "ai_complete", "arguments": {}}],
        )
        final_completion = FakeCompletionResult(
            content="done",
            total_tokens=20,
            cost_usd=0.0005,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(side_effect=[tool_call_completion, final_completion])

        # Return a very long string from the tool
        huge_output = "x" * 25_000
        tool_executor = AsyncMock(return_value=huge_output)

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            await runtime.run(
                messages=[{"role": "user", "content": "test"}],
                instance_id=INSTANCE_ID,
                tool_executor=tool_executor,
                governance_checker=None,
                db=None,
            )

        # Check the tool message in the second LLM call
        second_call_kwargs = mock_ai_gw.completion.call_args_list[1].kwargs
        tool_msgs = [m for m in second_call_kwargs["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"].endswith("... [truncated]")
        assert len(tool_msgs[0]["content"]) < 25_000

    @pytest.mark.asyncio
    async def test_emit_called_after_tool_step(self):
        """An AgentStepCompleted event is emitted after a tool call step."""
        runtime = _build_runtime()

        tool_call_completion = FakeCompletionResult(
            total_tokens=30,
            cost_usd=0.001,
            tool_calls=[{"id": "call_1", "name": "ai_complete", "arguments": {}}],
        )
        final_completion = FakeCompletionResult(
            content="done",
            total_tokens=20,
            cost_usd=0.0005,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(side_effect=[tool_call_completion, final_completion])

        mock_emit = AsyncMock()

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, mock_emit),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            await runtime.run(
                messages=[{"role": "user", "content": "test"}],
                instance_id=INSTANCE_ID,
                tool_executor=AsyncMock(return_value="ok"),
                governance_checker=None,
                db=None,
            )

        # emit should have been called at least once (for the tool step)
        mock_emit.assert_awaited()
        emitted_event = mock_emit.call_args_list[0].args[0]
        assert emitted_event.action == "tool_call"
        assert emitted_event.tool_name == "ai_complete"
        assert emitted_event.step_number == 1

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_single_step(self):
        """When the LLM returns multiple tool_calls, all are executed in the same step."""
        runtime = _build_runtime(allowed_tools=["ai_complete", "file_list"])

        multi_tool_completion = FakeCompletionResult(
            total_tokens=40,
            cost_usd=0.002,
            tool_calls=[
                {"id": "call_a", "name": "ai_complete", "arguments": {"messages": []}},
                {"id": "call_b", "name": "file_list", "arguments": {}},
            ],
        )
        final_completion = FakeCompletionResult(
            content="Both done",
            total_tokens=15,
            cost_usd=0.0003,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(side_effect=[multi_tool_completion, final_completion])

        tool_executor = AsyncMock(side_effect=["result_a", "result_b"])

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock()
            mock_registry.list_builtin_tools.return_value = {}

            result = await runtime.run(
                messages=[{"role": "user", "content": "do both"}],
                instance_id=INSTANCE_ID,
                tool_executor=tool_executor,
                governance_checker=None,
                db=None,
            )

        assert result.output == "Both done"
        assert result.finish_reason == "completed"
        # 2 tool_call steps + 1 response step
        assert len(result.steps) == 3
        assert result.steps[0].tool_name == "ai_complete"
        assert result.steps[1].tool_name == "file_list"
        assert result.steps[2].action == "response"

        # tool_executor was called twice
        assert tool_executor.await_count == 2

        # Verify both tool results appear in the conversation for the second LLM call
        second_call_kwargs = mock_ai_gw.completion.call_args_list[1].kwargs
        tool_msgs = [m for m in second_call_kwargs["messages"] if m.get("role") == "tool"]
        assert len(tool_msgs) == 2
        assert tool_msgs[0]["tool_call_id"] == "call_a"
        assert tool_msgs[1]["tool_call_id"] == "call_b"

    @pytest.mark.asyncio
    async def test_spending_tracking_failure_is_swallowed(self):
        """If GovernanceEngine.track_spending raises, the loop continues."""
        runtime = _build_runtime()

        completion = FakeCompletionResult(
            content="answer",
            total_tokens=20,
            cost_usd=0.0005,
            tool_calls=None,
        )

        mock_ai_gw = AsyncMock()
        mock_ai_gw.completion = AsyncMock(return_value=completion)

        with (
            patch(_PATCH_AI_GW, mock_ai_gw),
            patch(_PATCH_GOVERNANCE) as mock_gov,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_TOOL_REGISTRY) as mock_registry,
        ):
            mock_gov.track_spending = AsyncMock(side_effect=Exception("Redis down"))
            mock_registry.list_builtin_tools.return_value = {}

            result = await runtime.run(
                messages=[{"role": "user", "content": "test"}],
                instance_id=INSTANCE_ID,
                tool_executor=None,
                db=None,
            )

        # The loop should still complete successfully despite tracking failure
        assert result.finish_reason == "completed"
        assert result.output == "answer"
