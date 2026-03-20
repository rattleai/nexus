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
import contextlib
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.agents.events import AgentStepCompleted
from app.agents.models import AgentDefinition, AgentInstance
from app.config import settings
from app.core.events import emit

logger = structlog.stdlib.get_logger()

# OpenTelemetry tracing — returns a no-op context manager when OTEL is not available
try:
    from opentelemetry import trace
    _tracer = trace.get_tracer("app.agents.runtime")
except ImportError:
    _tracer = None

# Maximum characters for tool output before truncation.
_MAX_TOOL_OUTPUT = 20_000


def _otel_span(name: str, **attributes: Any) -> contextlib.AbstractContextManager:
    """Create an OTel span as a context manager, or a no-op if tracing is disabled."""
    if _tracer:
        return _tracer.start_as_current_span(name, attributes=attributes)
    return contextlib.nullcontext()


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
        self._tenant_tool_schemas: dict[str, dict[str, Any]] = {}

    def cancel(self) -> None:
        """Signal the runtime to stop after the current step."""
        self._cancelled = True

    async def _checkpoint_progress(
        self,
        instance_id: uuid.UUID,
        result: RunResult,
        step_num: int,
        db: Any,
    ) -> None:
        """Persist step progress and heartbeat in one write (Temporal heartbeat pattern).

        Combines liveness signal with incremental metrics persistence so that
        partial progress survives worker crashes.  Best-effort: failures are
        logged but never crash the run.
        """
        from datetime import datetime, UTC
        from sqlalchemy import update

        try:
            await db.execute(
                update(AgentInstance)
                .where(AgentInstance.id == instance_id)
                .values(
                    last_heartbeat_at=datetime.now(UTC),
                    steps_executed=len(result.steps),
                    tokens_used=result.total_tokens,
                    cost_usd=result.total_cost_usd,
                    last_checkpoint={
                        "step": step_num,
                        "finish_reason": result.finish_reason,
                        "ts": datetime.now(UTC).isoformat(),
                    },
                )
            )
            await db.flush()
        except Exception:
            logger.debug("checkpoint_write_failed", instance_id=str(instance_id))

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

        with _otel_span(
            "gen_ai.agent.run",
            **{
                "gen_ai.system": "cadprice",
                "gen_ai.agent.id": str(self.definition.id),
                "gen_ai.agent.name": self.definition.name,
                "gen_ai.request.model": self.definition.model,
                "gen_ai.agent.instance_id": str(instance_id),
                "gen_ai.tenant_id": str(self.tenant_id),
            },
        ) as run_span:
            result = RunResult()
            start_time = time.monotonic()

            # Preload tenant tool schemas so the LLM gets accurate function signatures
            if db is not None:
                await self._load_tenant_tool_schemas(db)

            # Build conversation with system messages + memory context
            conversation = self._build_conversation(messages)
            if db is not None:
                memory_context = await self._retrieve_memory_context(messages, instance_id, db)
                if memory_context:
                    conversation.insert(
                        1 if conversation and conversation[0].get("role") == "system" else 0,
                        {"role": "system", "content": memory_context},
                    )

            self._enforce_message_limits(conversation)

            max_steps = self.definition.max_steps_per_run
            max_tokens = self.definition.max_tokens_per_run
            tools_schema = self._build_tools_schema()

            for step_num in range(1, max_steps + 1):
                if self._cancelled:
                    result.finish_reason = "cancelled"
                    break

                if result.total_tokens >= max_tokens:
                    result.finish_reason = "max_tokens"
                    break

                if (time.monotonic() - start_time) > self.definition.max_duration_seconds:
                    result.finish_reason = "max_duration"
                    break

                step_start = time.monotonic()

                with _otel_span(
                    "gen_ai.agent.step",
                    **{
                        "gen_ai.agent.step_number": step_num,
                        "gen_ai.request.model": self.definition.model,
                        "gen_ai.agent.instance_id": str(instance_id),
                    },
                ) as step_span:
                    try:
                        step_result = await self._execute_step(
                            step_num=step_num,
                            conversation=conversation,
                            tools_schema=tools_schema,
                            tool_executor=tool_executor,
                            governance_checker=governance_checker,
                            instance_id=instance_id,
                            result=result,
                            ai_gateway=ai_gateway,
                            GovernanceEngine=GovernanceEngine,
                            db=db,
                            step_span=step_span,
                        )

                        step_duration = int((time.monotonic() - step_start) * 1000)

                        # Checkpoint progress after each step (heartbeat + partial metrics)
                        if db is not None:
                            await self._checkpoint_progress(instance_id, result, step_num, db)

                        if step_result == "break":
                            break
                        if step_result == "done":
                            break

                    except TimeoutError:
                        logger.warning(
                            "agent_llm_timeout",
                            instance_id=str(instance_id),
                            step=step_num,
                        )
                        result.finish_reason = "error"
                        result.steps.append(StepResult(
                            step_number=step_num,
                            action="error",
                            content=f"LLM call timed out after {settings.AI_REQUEST_TIMEOUT_SECONDS}s",
                            duration_ms=int((time.monotonic() - step_start) * 1000),
                        ))
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
                        result.steps.append(StepResult(
                            step_number=step_num,
                            action="error",
                            content=str(exc)[:500],
                            duration_ms=int((time.monotonic() - step_start) * 1000),
                        ))
                        if step_span:
                            step_span.set_attribute("error", True)
                            step_span.set_attribute("agent.error", str(exc)[:200])
                        break
            else:
                result.finish_reason = "max_steps"

            result.total_duration_ms = int((time.monotonic() - start_time) * 1000)

            # Record final metrics on the run span
            if run_span:
                with contextlib.suppress(Exception):
                    run_span.set_attribute("gen_ai.usage.total_tokens", result.total_tokens)
                    run_span.set_attribute("gen_ai.usage.cost_usd", result.total_cost_usd)
                    run_span.set_attribute("gen_ai.agent.total_steps", len(result.steps))
                    run_span.set_attribute("gen_ai.response.finish_reason", result.finish_reason)
                    run_span.set_attribute("gen_ai.agent.duration_ms", result.total_duration_ms)

            # Record OTel metrics for the completed run
            with contextlib.suppress(Exception):
                from app.core.otel_metrics import record_agent_run
                record_agent_run(
                    agent_name=self.definition.name,
                    status=result.finish_reason,
                    tokens=result.total_tokens,
                    cost_usd=result.total_cost_usd,
                    steps=len(result.steps),
                )

            # Store significant output in long-term memory for future retrieval
            if db is not None and result.output and result.finish_reason == "completed":
                with contextlib.suppress(Exception):
                    await self._store_output_to_memory(result, instance_id, db)

            return result

    async def _execute_step(
        self,
        *,
        step_num: int,
        conversation: list[dict[str, Any]],
        tools_schema: list[dict] | None,
        tool_executor: Any | None,
        governance_checker: Any | None,
        instance_id: uuid.UUID,
        result: RunResult,
        ai_gateway: Any,
        GovernanceEngine: Any,
        db: Any | None,
        step_span: Any,
    ) -> str:
        """Execute one ReAct step. Returns "done", "break", or "continue"."""
        step_start = time.monotonic()
        llm_timeout = settings.AI_REQUEST_TIMEOUT_SECONDS

        completion = await asyncio.wait_for(
            ai_gateway.completion(
                tenant_id=self.tenant_id,
                model=self.definition.model,
                messages=conversation,
                api_key=self.api_key,
                key_source=self.key_source,
                max_tokens=self.definition.max_tokens,
                temperature=self.definition.temperature,
                db=db,
                tools=tools_schema,
            ),
            timeout=llm_timeout,
        )

        step_tokens = completion.total_tokens
        step_cost = completion.cost_usd
        result.total_tokens += step_tokens
        result.total_cost_usd += step_cost

        # Record metrics on OTel span
        if step_span:
            step_span.set_attribute("gen_ai.usage.total_tokens", step_tokens)
            step_span.set_attribute("gen_ai.usage.cost_usd", step_cost)

        # Track spending (best-effort)
        with contextlib.suppress(Exception):
            await GovernanceEngine.track_spending(
                tenant_id=self.tenant_id,
                agent_id=str(self.definition.id),
                instance_id=str(instance_id),
                cost_usd=step_cost,
            )

        # Check if the LLM wants to call a tool
        tool_calls = self._extract_tool_calls(completion)

        if tool_calls and tool_executor:
            # Append assistant message with tool_calls for proper API format
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if completion.content:
                assistant_msg["content"] = completion.content
            if completion.tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc_raw["id"],
                        "type": "function",
                        "function": {
                            "name": tc_raw["name"],
                            "arguments": (
                                tc_raw["arguments"] if isinstance(tc_raw["arguments"], str)
                                else json.dumps(tc_raw["arguments"])
                            ),
                        },
                    }
                    for tc_raw in completion.tool_calls
                ]
            conversation.append(assistant_msg)

            # Execute all tool calls from this LLM response
            use_parallel = (
                len(tool_calls) > 1
                and getattr(self.definition, "parallel_tool_execution", True)
            )

            if use_parallel:
                # Parallel execution via asyncio.gather
                tool_results_list = await self._run_tools_parallel(
                    tool_calls, tool_executor, governance_checker,
                    instance_id, step_num, result,
                )
            else:
                # Sequential execution
                tool_results_list = await self._run_tools_sequential(
                    tool_calls, tool_executor, governance_checker,
                    instance_id, step_num, result,
                )

            # Process results in order: append to conversation, record steps
            for tc, tool_result in zip(tool_calls, tool_results_list):
                tool_result_str = str(tool_result)
                if len(tool_result_str) > _MAX_TOOL_OUTPUT:
                    tool_result_str = tool_result_str[:_MAX_TOOL_OUTPUT] + "... [truncated]"

                step_duration = int((time.monotonic() - step_start) * 1000)
                result.steps.append(StepResult(
                    step_number=step_num,
                    action="tool_call",
                    tool_name=tc.name,
                    tool_result=tool_result,
                    tokens_used=step_tokens,
                    cost_usd=step_cost,
                    duration_ms=step_duration,
                ))

                conversation.append({
                    "role": "tool",
                    "tool_call_id": tc.call_id,
                    "content": tool_result_str,
                })

                # Emit step event (best-effort)
                with contextlib.suppress(Exception):
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

            if step_span:
                step_span.set_attribute("agent.action", "tool_call")
            return "continue"

        else:
            # LLM responded directly — agent run is complete
            output_content = completion.content

            # Validate output against schema and content policy
            from app.agents.validation import validate_agent_output
            is_valid, validation_errors, sanitized = validate_agent_output(
                output_content,
                governance_policy=self.definition.governance_policy,
                output_schema=self.definition.output_schema or None,
            )

            if not is_valid:
                logger.warning(
                    "agent_output_validation_failed",
                    errors=validation_errors,
                    instance_id=str(instance_id),
                )
                if step_span:
                    step_span.set_attribute("agent.validation_errors", len(validation_errors))

            # Use sanitized output (PII redacted if configured)
            output_content = sanitized

            result.steps.append(StepResult(
                step_number=step_num,
                action="response",
                content=output_content,
                tokens_used=step_tokens,
                cost_usd=step_cost,
            ))
            result.output = output_content
            result.finish_reason = "completed"
            if step_span:
                step_span.set_attribute("agent.action", "response")
            return "done"

    # ── Tool execution helpers ───────────────────────────────────────────

    async def _run_one_tool(
        self,
        tc: ToolCall,
        tool_executor: Any,
        governance_checker: Any | None,
        instance_id: uuid.UUID,
        step_num: int,
        result: RunResult,
    ) -> Any:
        """Execute a single tool call with governance check, timeout, and OTel span."""
        if governance_checker:
            await governance_checker(
                action="tool_call",
                context={
                    "tool_name": tc.name,
                    "instance_id": str(instance_id),
                    "agent_id": str(self.definition.id),
                    "step_number": step_num,
                    "current_cost": result.total_cost_usd,
                },
            )

        tool_start = time.monotonic()
        with _otel_span("gen_ai.agent.tool_call", **{"gen_ai.tool.name": tc.name}):
            try:
                tool_result = await asyncio.wait_for(
                    tool_executor(tc.name, tc.arguments),
                    timeout=settings.AGENT_TOOL_EXECUTION_TIMEOUT,
                )
            except TimeoutError:
                tool_result = {
                    "error": f"Tool '{tc.name}' timed out after "
                    f"{settings.AGENT_TOOL_EXECUTION_TIMEOUT}s",
                }

        # Record OTel tool duration metric
        tool_duration = int((time.monotonic() - tool_start) * 1000)
        with contextlib.suppress(Exception):
            from app.core.otel_metrics import record_tool_call
            record_tool_call(tool_name=tc.name, duration_ms=tool_duration)

        return tool_result

    async def _run_tools_parallel(
        self,
        tool_calls: list[ToolCall],
        tool_executor: Any,
        governance_checker: Any | None,
        instance_id: uuid.UUID,
        step_num: int,
        result: RunResult,
    ) -> list[Any]:
        """Execute multiple tool calls concurrently via asyncio.gather."""
        coros = [
            self._run_one_tool(tc, tool_executor, governance_checker, instance_id, step_num, result)
            for tc in tool_calls
        ]
        raw_results = await asyncio.gather(*coros, return_exceptions=True)

        # Convert exceptions to error dicts
        final = []
        for i, r in enumerate(raw_results):
            if isinstance(r, Exception):
                final.append({"error": f"Tool '{tool_calls[i].name}' failed: {str(r)[:500]}"})
            else:
                final.append(r)
        return final

    async def _run_tools_sequential(
        self,
        tool_calls: list[ToolCall],
        tool_executor: Any,
        governance_checker: Any | None,
        instance_id: uuid.UUID,
        step_num: int,
        result: RunResult,
    ) -> list[Any]:
        """Execute tool calls one at a time (original behavior).

        Governance and runtime errors propagate to the caller (terminates run).
        Only tool execution errors are caught and converted to error dicts.
        """
        results_list = []
        for tc in tool_calls:
            # Governance check runs inside _run_one_tool and its errors
            # must propagate to terminate the run
            r = await self._run_one_tool(tc, tool_executor, governance_checker, instance_id, step_num, result)
            results_list.append(r)
        return results_list

    # ── Streaming support ─────────────────────────────────────────────────

    async def run_stream(
        self,
        *,
        messages: list[dict[str, Any]],
        instance_id: uuid.UUID,
        tool_executor: Any | None = None,
        governance_checker: Any | None = None,
        db: Any | None = None,
    ):
        """Execute the ReAct loop, yielding SSE events at each stage.

        Yields dicts with 'event' and 'data' keys suitable for SSE formatting.
        """
        from app.agents.governance import GovernanceEngine
        from app.ai.gateway import ai_gateway

        yield {"event": "run_started", "data": {"instance_id": str(instance_id), "agent_id": str(self.definition.id)}}

        result = RunResult()
        start_time = time.monotonic()

        if db is not None:
            await self._load_tenant_tool_schemas(db)

        conversation = self._build_conversation(messages)
        if db is not None:
            memory_context = await self._retrieve_memory_context(messages, instance_id, db)
            if memory_context:
                conversation.insert(
                    1 if conversation and conversation[0].get("role") == "system" else 0,
                    {"role": "system", "content": memory_context},
                )

        self._enforce_message_limits(conversation)

        max_steps = self.definition.max_steps_per_run
        max_tokens = self.definition.max_tokens_per_run
        tools_schema = self._build_tools_schema()

        for step_num in range(1, max_steps + 1):
            if self._cancelled:
                yield {"event": "run_completed", "data": {"finish_reason": "cancelled", "output": result.output}}
                return

            if result.total_tokens >= max_tokens:
                yield {"event": "run_completed", "data": {"finish_reason": "max_tokens", "output": result.output}}
                return

            yield {"event": "step_started", "data": {"step_number": step_num}}

            try:
                completion = await asyncio.wait_for(
                    ai_gateway.completion(
                        tenant_id=self.tenant_id,
                        model=self.definition.model,
                        messages=conversation,
                        api_key=self.api_key,
                        key_source=self.key_source,
                        max_tokens=self.definition.max_tokens,
                        temperature=self.definition.temperature,
                        db=db,
                        tools=tools_schema,
                    ),
                    timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                yield {"event": "error", "data": {"message": "LLM call timed out"}}
                yield {"event": "run_completed", "data": {"finish_reason": "error", "output": ""}}
                return
            except Exception as exc:
                yield {"event": "error", "data": {"message": str(exc)[:500]}}
                yield {"event": "run_completed", "data": {"finish_reason": "error", "output": ""}}
                return

            step_tokens = completion.total_tokens
            step_cost = completion.cost_usd
            result.total_tokens += step_tokens
            result.total_cost_usd += step_cost

            yield {"event": "thinking", "data": {"tokens": step_tokens, "cost_usd": step_cost}}

            with contextlib.suppress(Exception):
                await GovernanceEngine.track_spending(
                    tenant_id=self.tenant_id,
                    agent_id=str(self.definition.id),
                    instance_id=str(instance_id),
                    cost_usd=step_cost,
                )

            tool_calls = self._extract_tool_calls(completion)

            if tool_calls and tool_executor:
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if completion.content:
                    assistant_msg["content"] = completion.content
                    yield {"event": "content_delta", "data": {"content": completion.content}}
                if completion.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {"id": tc_raw["id"], "type": "function", "function": {"name": tc_raw["name"], "arguments": tc_raw["arguments"] if isinstance(tc_raw["arguments"], str) else json.dumps(tc_raw["arguments"])}}
                        for tc_raw in completion.tool_calls
                    ]
                conversation.append(assistant_msg)

                for tc in tool_calls:
                    yield {"event": "tool_call", "data": {"tool_name": tc.name, "arguments": tc.arguments}}

                    try:
                        tool_result = await asyncio.wait_for(
                            tool_executor(tc.name, tc.arguments),
                            timeout=settings.AGENT_TOOL_EXECUTION_TIMEOUT,
                        )
                    except TimeoutError:
                        tool_result = {"error": f"Tool '{tc.name}' timed out"}

                    yield {"event": "tool_result", "data": {"tool_name": tc.name, "result": str(tool_result)[:2000]}}

                    conversation.append({"role": "tool", "tool_call_id": tc.call_id, "content": str(tool_result)[:_MAX_TOOL_OUTPUT]})

                yield {"event": "step_completed", "data": {"step_number": step_num, "action": "tool_call"}}

                # Checkpoint progress after each step (heartbeat + partial metrics)
                if db is not None:
                    await self._checkpoint_progress(instance_id, result, step_num, db)
            else:
                output_content = completion.content
                from app.agents.validation import validate_agent_output
                _, _, sanitized = validate_agent_output(
                    output_content,
                    governance_policy=self.definition.governance_policy,
                    output_schema=self.definition.output_schema or None,
                )
                result.output = sanitized
                yield {"event": "content_delta", "data": {"content": sanitized}}
                yield {"event": "step_completed", "data": {"step_number": step_num, "action": "response"}}

                # Final checkpoint before completion
                if db is not None:
                    await self._checkpoint_progress(instance_id, result, step_num, db)

                yield {"event": "run_completed", "data": {
                    "finish_reason": "completed",
                    "output": sanitized,
                    "total_tokens": result.total_tokens,
                    "total_cost_usd": result.total_cost_usd,
                }}
                return

        yield {"event": "run_completed", "data": {"finish_reason": "max_steps", "output": result.output}}

    # ── Conversation building ────────────────────────────────────────────

    def _build_conversation(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build initial conversation with system prompt."""
        system_messages: list[dict[str, Any]] = []
        if self.definition.system_prompt:
            system_messages.append({"role": "system", "content": self.definition.system_prompt})
        return system_messages + list(messages)

    def _enforce_message_limits(self, conversation: list[dict[str, Any]]) -> None:
        """Truncate oversized messages and cap conversation length."""
        max_msg_len = settings.AI_MAX_MESSAGE_LENGTH
        for msg in conversation:
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > max_msg_len:
                msg["content"] = content[:max_msg_len] + "... [truncated]"

        _max_conv = settings.AGENT_MAX_CONVERSATION_MESSAGES
        if len(conversation) > _max_conv:
            sys_msgs = [m for m in conversation if m.get("role") == "system"]
            non_sys = [m for m in conversation if m.get("role") != "system"]
            budget = max(1, _max_conv - len(sys_msgs))
            conversation[:] = sys_msgs + non_sys[-budget:]

    # ── Tool calls ───────────────────────────────────────────────────────

    def _extract_tool_calls(self, completion: Any) -> list[ToolCall]:
        """Extract tool calls from the AI gateway completion result."""
        if not completion.tool_calls:
            return []
        return [
            ToolCall(
                name=tc["name"],
                arguments=tc.get("arguments", {}),
                call_id=tc.get("id", ""),
            )
            for tc in completion.tool_calls
        ]

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
            elif tool_name in self._tenant_tool_schemas:
                info = self._tenant_tool_schemas[tool_name]
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": info.get("description", f"Custom tool: {tool_name}"),
                        "parameters": info.get("input_schema", {"type": "object", "properties": {}}),
                    },
                })
            else:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": f"Custom tool: {tool_name}",
                        "parameters": {"type": "object", "properties": {}},
                    },
                })
        return tools if tools else None

    async def _load_tenant_tool_schemas(self, db: Any) -> None:
        """Preload tenant tool schemas from DB so _build_tools_schema uses real schemas."""
        from app.agents.tool_registry import tool_registry

        allowed = self.definition.allowed_tools or []
        builtin_names = set(tool_registry.list_builtin_tools().keys())
        tenant_tool_names = [n for n in allowed if n not in builtin_names]

        if not tenant_tool_names:
            return

        try:
            from sqlalchemy import select
            from app.agents.models import TenantTool

            stmt = select(TenantTool).where(
                TenantTool.tenant_id == self.tenant_id,
                TenantTool.tool_name.in_(tenant_tool_names),
                TenantTool.is_active.is_(True),
                TenantTool.deleted_at.is_(None),
            )
            result = await db.execute(stmt)
            pinned_versions = self.definition.tool_versions or {}

            for tool in result.scalars().all():
                # Enforce tool version pinning
                if tool.tool_name in pinned_versions:
                    pinned = pinned_versions[tool.tool_name]
                    if tool.version != pinned:
                        raise RuntimeError(
                            f"Tool '{tool.tool_name}' version mismatch: "
                            f"agent pins v{pinned} but tenant has v{tool.version}. "
                            f"Update the agent's tool_versions or the tool."
                        )

                self._tenant_tool_schemas[tool.tool_name] = {
                    "description": tool.description,
                    "input_schema": tool.input_schema or {"type": "object", "properties": {}},
                    "version": tool.version,
                }
        except RuntimeError:
            raise  # Re-raise version mismatch errors
        except Exception:
            logger.warning("tenant_tool_schema_load_failed", tenant_id=str(self.tenant_id), exc_info=True)

    # ── Memory integration ───────────────────────────────────────────────

    async def _retrieve_memory_context(
        self,
        messages: list[dict[str, Any]],
        instance_id: uuid.UUID,
        db: Any,
    ) -> str:
        """Retrieve relevant long-term memory context for the current conversation."""
        memory_config = self.definition.memory_config or {}
        if not memory_config.get("enabled", False):
            return ""

        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            return ""

        query = user_messages[-1].get("content", "")
        if not query or not isinstance(query, str):
            return ""

        try:
            from app.agents.embeddings import rag_pipeline

            results = await rag_pipeline.retrieve(
                query=query[:2000],
                instance_id=instance_id,
                tenant_id=self.tenant_id,
                namespace=memory_config.get("namespace", "rag"),
                limit=memory_config.get("rag_limit", 5),
                db=db,
            )
            context_parts = []
            rag_context = rag_pipeline.format_context(results)
            if rag_context:
                context_parts.append(rag_context)

            # Retrieve definition-scoped shared memory (cross-instance knowledge)
            if memory_config.get("shared_memory_enabled", False):
                try:
                    from app.agents.memory import AgentMemoryManager
                    mem = AgentMemoryManager(db)
                    shared_entries = await mem.list_definition_memory(
                        definition_id=self.definition.id,
                        tenant_id=self.tenant_id,
                        namespace=memory_config.get("shared_namespace", "shared"),
                        limit=memory_config.get("shared_memory_limit", 10),
                    )
                    if shared_entries:
                        lines = ["[Shared agent memory (accessible by all instances of this agent):"]
                        for entry in shared_entries:
                            lines.append(f"- {entry.key}: {entry.value}")
                        lines.append("]")
                        context_parts.append("\n".join(lines))
                except Exception:
                    logger.debug("shared_memory_retrieval_failed", exc_info=True)

            return "\n\n".join(context_parts)
        except Exception:
            logger.debug("memory_context_retrieval_failed", exc_info=True)
            return ""

    async def _store_output_to_memory(
        self,
        result: RunResult,
        instance_id: uuid.UUID,
        db: Any,
    ) -> None:
        """Store significant run output in long-term memory."""
        memory_config = self.definition.memory_config or {}
        if not memory_config.get("store_outputs", False):
            return

        from app.agents.memory import AgentMemoryManager

        memory = AgentMemoryManager(db)
        output_hash = hashlib.sha256(result.output[:1000].encode()).hexdigest()[:12]

        await memory.set_long_term(
            instance_id=instance_id,
            tenant_id=self.tenant_id,
            key=f"output:{output_hash}",
            value={
                "output": result.output[:5000],
                "steps": len(result.steps),
                "cost_usd": result.total_cost_usd,
                "finish_reason": result.finish_reason,
            },
            namespace=memory_config.get("namespace", "outputs"),
        )
        await db.flush()
