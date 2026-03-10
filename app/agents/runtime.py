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
        from app.ai.gateway import ai_gateway

        result = RunResult()
        start_time = time.monotonic()

        # Build system message from definition
        system_messages = []
        if self.definition.system_prompt:
            system_messages.append({"role": "system", "content": self.definition.system_prompt})

        conversation = system_messages + list(messages)

        max_steps = self.definition.max_steps_per_run
        max_tokens = self.definition.max_tokens_per_run

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
                )

                step_tokens = completion.total_tokens
                step_cost = completion.cost_usd
                result.total_tokens += step_tokens
                result.total_cost_usd += step_cost

                # Check if the LLM wants to call a tool
                tool_calls = self._extract_tool_calls(completion.content)

                if tool_calls and tool_executor:
                    # Execute tool calls
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

                        tool_result = await tool_executor(tc.name, tc.arguments)

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

                        # Append tool result to conversation for next iteration
                        conversation.append({"role": "assistant", "content": completion.content})
                        conversation.append({
                            "role": "user",
                            "content": f"Tool '{tc.name}' returned: {tool_result}",
                        })

                        # Emit step event
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
                break
        else:
            result.finish_reason = "max_steps"

        result.total_duration_ms = int((time.monotonic() - start_time) * 1000)
        return result

    def _extract_tool_calls(self, content: str) -> list[ToolCall]:
        """Extract tool calls from LLM response content.

        Supports multiple formats:
        1. JSON tool_call blocks (OpenAI-style)
        2. XML-style <tool_call> tags
        3. Markdown code blocks with tool invocations

        This is a simplified extraction. In production, tool_calls come from
        the LLM response object's tool_calls field, not content parsing.
        """
        # For now, return empty — actual tool calls come from LiteLLM's
        # response.choices[0].message.tool_calls which the AI gateway
        # would need to expose. This is a placeholder for the extraction logic.
        return []
