"""Agent execution runtime — the core ReAct loop that drives agent reasoning.

Implements a Reason-Act-Observe loop:
    1. Send conversation + system prompt to LLM
    2. LLM decides: respond (done) or call a tool (act)
    3. Execute the tool, observe the result
    4. Append observation, goto 1

Integrates with:
    - app.ai.gateway for LLM calls
    - app.agents.tool_registry for tool resolution
    - app.agents.governance for policy enforcement
    - app.agents.memory for context management
    - app.core.event_bus for durable event emission
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.agents.events import AgentStepCompleted
from app.agents.models import AgentDefinition
from app.config import settings
from app.core.events import emit

logger = structlog.stdlib.get_logger()


@dataclass
class ToolCall:
    """A tool invocation requested by the LLM."""

    name: str
    arguments: dict[str, Any]
    call_id: str = ""


@dataclass
class StepResult:
    """Result of a single agent step (one LLM call + optional tool execution)."""

    step_number: int
    action: str  # "tool_call" or "response"
    content: str = ""
    tool_name: str = ""
    tool_result: Any = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0


@dataclass
class RunResult:
    """Final result of a complete agent run."""

    output: str = ""
    steps: list[StepResult] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    finish_reason: str = "completed"  # "completed", "max_steps", "max_tokens", "cancelled", "error"


class AgentRuntime:
    """Core agent execution runtime implementing the ReAct loop.

    This is the central execution engine. It is application-agnostic — it does
    not know what tools exist or what the agent is supposed to do. It simply
    executes the loop: LLM → tool call → observe → repeat.
    """

    def __init__(
        self,
        *,
        definition: AgentDefinition,
        tenant_id: uuid.UUID,
        api_key: str,
        key_source: str = "platform",
    ):
        self.definition = definition
        self.tenant_id = tenant_id
        self.api_key = api_key
        self.key_source = key_source
        self._cancelled = False

    def cancel(self) -> None:
        """Signal the runtime to stop after the current step."""
        self._cancelled = True

    async def run(
        self,
        *,
        messages: list[dict[str, Any]],
        instance_id: uuid.UUID,
        tool_executor: Any | None = None,
        governance_checker: Any | None = None,
        db: Any | None = None,
    ) -> RunResult:
        """Execute the agent's ReAct loop until completion or limit reached.

        Args:
            messages: Initial conversation messages (user input).
            instance_id: The agent instance ID (for event tracking).
            tool_executor: Callable(tool_name, arguments) → result.
            governance_checker: Callable(action, context) → bool (raises on violation).
            db: Database session for AI gateway.
        """
        from app.agents.governance import GovernanceEngine
        from app.ai.gateway import ai_gateway

        result = RunResult()
        start_time = time.monotonic()

        # Build system message from definition
        system_messages = []
        if self.definition.system_prompt:
            system_messages.append({"role": "system", "content": self.definition.system_prompt})

        conversation = system_messages + list(messages)

        # Guard against unbounded conversation growth
        _max_conv = settings.AGENT_MAX_CONVERSATION_MESSAGES
        if len(conversation) > _max_conv:
            sys_msgs = [m for m in conversation if m.get("role") == "system"]
            conversation = sys_msgs + conversation[-(max(1, _max_conv - len(sys_msgs))):]

        max_steps = self.definition.max_steps_per_run
        max_tokens = self.definition.max_tokens_per_run

        # Build tools schema for LLM function calling
        tools_schema = self._build_tools_schema()

        for step_num in range(1, max_steps + 1):
            if self._cancelled:
                result.finish_reason = "cancelled"
                break

            if result.total_tokens >= max_tokens:
                result.finish_reason = "max_tokens"
                break

            elapsed = time.monotonic() - start_time
            if elapsed > self.definition.max_duration_seconds:
                result.finish_reason = "max_duration"
                break

            step_start = time.monotonic()

            try:
                # Call LLM
                completion = await ai_gateway.completion(
                    tenant_id=self.tenant_id,
                    model=self.definition.model,
                    messages=conversation,
                    api_key=self.api_key,
                    key_source=self.key_source,
                    max_tokens=self.definition.max_tokens,
                    temperature=self.definition.temperature,
                    db=db,
                    tools=tools_schema,
                )

                step_tokens = completion.total_tokens
                step_cost = completion.cost_usd
                result.total_tokens += step_tokens
                result.total_cost_usd += step_cost

                # Track spending after each LLM call (best-effort)
                try:
                    await GovernanceEngine.track_spending(
                        tenant_id=self.tenant_id,
                        agent_id=str(self.definition.id),
                        instance_id=str(instance_id),
                        cost_usd=step_cost,
                    )
                except Exception:
                    pass

                # Check if the LLM wants to call a tool
                tool_calls = self._extract_tool_calls(completion)

                if tool_calls and tool_executor:
                    # Append assistant message with tool_calls for proper API format
                    assistant_msg: dict[str, Any] = {"role": "assistant"}
                    if completion.content:
                        assistant_msg["content"] = completion.content
                    # Include tool_calls in assistant message for LLM context
                    if completion.tool_calls:
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc_raw["id"],
                                "type": "function",
                                "function": {
                                    "name": tc_raw["name"],
                                    "arguments": (
                                        tc_raw["arguments"] if isinstance(tc_raw["arguments"], str)
                                        else __import__("json").dumps(tc_raw["arguments"])
                                    ),
                                },
                            }
                            for tc_raw in completion.tool_calls
                        ]
                    conversation.append(assistant_msg)

                    # Execute all tool calls from this LLM response
                    for tc in tool_calls:
                        # Governance check before tool execution
                        if governance_checker:
                            await governance_checker(
                                action="tool_call",
                                context={
                                    "tool_name": tc.name,
                                    "instance_id": str(instance_id),
                                    "step_number": step_num,
                                    "current_cost": result.total_cost_usd,
                                },
                            )

                        try:
                            tool_result = await asyncio.wait_for(
                                tool_executor(tc.name, tc.arguments),
                                timeout=settings.AGENT_TOOL_EXECUTION_TIMEOUT,
                            )
                        except asyncio.TimeoutError:
                            tool_result = {
                                "error": f"Tool '{tc.name}' timed out after "
                                f"{settings.AGENT_TOOL_EXECUTION_TIMEOUT}s",
                            }

                        # Truncate oversized tool output to prevent token/memory exhaustion.
                        _MAX_TOOL_OUTPUT = 20_000  # characters
                        tool_result_str = str(tool_result)
                        if len(tool_result_str) > _MAX_TOOL_OUTPUT:
                            tool_result_str = tool_result_str[:_MAX_TOOL_OUTPUT] + "... [truncated]"

                        step_duration = int((time.monotonic() - step_start) * 1000)
                        step = StepResult(
                            step_number=step_num,
                            action="tool_call",
                            tool_name=tc.name,
                            tool_result=tool_result,
                            tokens_used=step_tokens,
                            cost_usd=step_cost,
                            duration_ms=step_duration,
                        )
                        result.steps.append(step)

                        # Append tool result using proper "tool" role for LLM API compatibility
                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tc.call_id,
                            "content": tool_result_str,
                        })

                        # Emit step event (best-effort)
                        try:
                            await emit(
                                AgentStepCompleted(
                                    tenant_id=str(self.tenant_id),
                                    instance_id=str(instance_id),
                                    step_number=step_num,
                                    action="tool_call",
                                    tool_name=tc.name,
                                    tokens_used=step_tokens,
                                    cost_usd=step_cost,
                                ),
                                durable=True,
                            )
                        except Exception:
                            pass
                else:
                    # LLM responded directly — agent run is complete
                    step_duration = int((time.monotonic() - step_start) * 1000)
                    step = StepResult(
                        step_number=step_num,
                        action="response",
                        content=completion.content,
                        tokens_used=step_tokens,
                        cost_usd=step_cost,
                        duration_ms=step_duration,
                    )
                    result.steps.append(step)
                    result.output = completion.content
                    result.finish_reason = "completed"
                    break

            except Exception as exc:
                logger.error(
                    "agent_step_failed",
                    instance_id=str(instance_id),
                    step=step_num,
                    error=str(exc),
                    exc_info=True,
                )
                result.finish_reason = "error"
                # Include error context in the result for debugging
                result.steps.append(StepResult(
                    step_number=step_num,
                    action="error",
                    content=str(exc)[:500],
                    duration_ms=int((time.monotonic() - step_start) * 1000),
                ))
                break
        else:
            result.finish_reason = "max_steps"

        result.total_duration_ms = int((time.monotonic() - start_time) * 1000)
        return result

    def _extract_tool_calls(self, completion) -> list[ToolCall]:
        """Extract tool calls from the AI gateway completion result.

        Reads from the structured tool_calls field populated by the AI gateway
        from LiteLLM's response.choices[0].message.tool_calls.
        """
        if not completion.tool_calls:
            return []

        calls = []
        for tc in completion.tool_calls:
            calls.append(ToolCall(
                name=tc["name"],
                arguments=tc.get("arguments", {}),
                call_id=tc.get("id", ""),
            ))
        return calls

    def _build_tools_schema(self) -> list[dict] | None:
        """Build OpenAI-compatible tools schema from allowed_tools."""
        allowed = self.definition.allowed_tools or []
        if not allowed:
            return None

        from app.agents.tool_registry import tool_registry
        builtin_tools = tool_registry.list_builtin_tools()

        tools = []
        for tool_name in allowed:
            if tool_name in builtin_tools:
                info = builtin_tools[tool_name]
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": info.get("description", ""),
                        "parameters": info.get("input_schema", {"type": "object", "properties": {}}),
                    },
                })
            else:
                # Tenant tools will be resolved at invocation time; provide
                # a generic schema so the LLM knows the tool exists.
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": f"Custom tool: {tool_name}",
                        "parameters": {"type": "object", "properties": {}},
                    },
                })
        return tools if tools else None
