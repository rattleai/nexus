"""Agent lifecycle executor — manages the full execution lifecycle of an agent instance.

Responsibilities:
    - Create and configure agent instances
    - Set up governance, memory, and tool access
    - Invoke the runtime (ReAct loop)
    - Persist results and emit events
    - Handle cleanup on completion/failure

This is the primary entry point for running an agent, whether synchronously
via an API request or asynchronously via a Celery task.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.events import (
    AgentInstanceCompleted,
    AgentInstanceFailed,
    AgentInstanceStarted,
    AgentInstanceStopped,
)
from app.agents.models import (
    AgentDefinition,
    AgentInstance,
    AgentSession,
    AgentStatus,
    InstanceStatus,
    SessionStatus,
)
from app.agents.runtime import AgentRuntime, RunResult
from app.core.events import emit
from app.db.session import set_tenant_context

logger = structlog.stdlib.get_logger()


class AgentExecutionError(Exception):
    """Raised when agent execution fails."""


class AgentExecutor:
    """Manages the full lifecycle of an agent instance execution.

    Usage:
        executor = AgentExecutor(db)
        result = await executor.run(
            definition_id=...,
            tenant_id=...,
            input_data={"messages": [{"role": "user", "content": "Hello"}]},
            api_key="...",
        )
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run(
        self,
        *,
        definition_id: uuid.UUID,
        tenant_id: uuid.UUID,
        input_data: dict[str, Any],
        api_key: str,
        key_source: str = "platform",
        session_id: uuid.UUID | None = None,
    ) -> AgentInstance:
        """Execute an agent from start to finish.

        1. Load definition
        2. Create instance + session
        3. Set up governance and tool access
        4. Run the ReAct loop
        5. Persist results
        6. Emit completion/failure events
        """
        await set_tenant_context(self.db, str(tenant_id))

        # Load definition
        definition = await self._load_definition(definition_id)
        if not definition:
            raise AgentExecutionError(f"Agent definition {definition_id} not found")
        if definition.status != AgentStatus.ACTIVE:
            raise AgentExecutionError(f"Agent '{definition.name}' is not active (status={definition.status.value})")

        # Create instance
        instance = AgentInstance(
            tenant_id=tenant_id,
            definition_id=definition_id,
            status=InstanceStatus.RUNNING,
            input_data=input_data,
            started_at=datetime.now(UTC),
        )
        self.db.add(instance)

        # Create or resume session
        session = await self._get_or_create_session(instance, tenant_id, session_id)
        self.db.add(session)

        await self.db.flush()

        # Emit start event
        await emit(
            AgentInstanceStarted(
                tenant_id=str(tenant_id),
                instance_id=str(instance.id),
                agent_id=str(definition_id),
                input_summary=str(input_data)[:200],
            ),
            durable=True,
        )

        # Build messages from input_data
        messages = input_data.get("messages", [])
        if not messages and "prompt" in input_data:
            messages = [{"role": "user", "content": input_data["prompt"]}]

        # Include session history for context continuity
        if session.messages:
            messages = list(session.messages) + messages

        # Set up tool executor
        tool_executor = await self._build_tool_executor(definition, tenant_id)

        # Set up governance checker
        governance_checker = await self._build_governance_checker(definition, tenant_id)

        # Run the agent
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=tenant_id,
            api_key=api_key,
            key_source=key_source,
        )

        try:
            result = await runtime.run(
                messages=messages,
                instance_id=instance.id,
                tool_executor=tool_executor,
                governance_checker=governance_checker,
                db=self.db,
            )

            # Update instance with results
            instance.status = (
                InstanceStatus.COMPLETED
                if result.finish_reason == "completed"
                else InstanceStatus.FAILED
                if result.finish_reason == "error"
                else InstanceStatus.COMPLETED
            )
            instance.output_data = {
                "output": result.output,
                "finish_reason": result.finish_reason,
                "steps_count": len(result.steps),
            }
            instance.steps_executed = len(result.steps)
            instance.tokens_used = result.total_tokens
            instance.cost_usd = result.total_cost_usd
            instance.completed_at = datetime.now(UTC)

            # Update session with new messages
            new_messages = list(session.messages or [])
            for step in result.steps:
                if step.action == "response" and step.content:
                    new_messages.append({"role": "assistant", "content": step.content})
                elif step.action == "tool_call":
                    new_messages.append({
                        "role": "assistant",
                        "content": f"[Tool: {step.tool_name}] → {step.tool_result}",
                    })
            session.messages = new_messages

            await self.db.commit()

            # Emit completion event
            await emit(
                AgentInstanceCompleted(
                    tenant_id=str(tenant_id),
                    instance_id=str(instance.id),
                    agent_id=str(definition_id),
                    steps_executed=instance.steps_executed,
                    tokens_used=instance.tokens_used,
                    cost_usd=instance.cost_usd,
                    duration_seconds=result.total_duration_ms / 1000,
                ),
                durable=True,
            )

            logger.info(
                "agent_execution_completed",
                instance_id=str(instance.id),
                agent_id=str(definition_id),
                steps=instance.steps_executed,
                tokens=instance.tokens_used,
                cost_usd=instance.cost_usd,
                finish_reason=result.finish_reason,
            )

        except Exception as exc:
            instance.status = InstanceStatus.FAILED
            instance.error = str(exc)[:2000]
            instance.completed_at = datetime.now(UTC)
            await self.db.commit()

            await emit(
                AgentInstanceFailed(
                    tenant_id=str(tenant_id),
                    instance_id=str(instance.id),
                    agent_id=str(definition_id),
                    error=str(exc)[:500],
                    step_number=instance.steps_executed,
                ),
                durable=True,
            )

            logger.error(
                "agent_execution_failed",
                instance_id=str(instance.id),
                agent_id=str(definition_id),
                error=str(exc),
                exc_info=True,
            )
            raise AgentExecutionError(str(exc)) from exc

        return instance

    async def stop(
        self,
        *,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reason: str = "user_requested",
    ) -> AgentInstance:
        """Stop a running agent instance."""
        await set_tenant_context(self.db, str(tenant_id))

        instance = await self.db.get(AgentInstance, instance_id)
        if not instance:
            raise AgentExecutionError(f"Instance {instance_id} not found")

        if instance.status != InstanceStatus.RUNNING:
            raise AgentExecutionError(
                f"Instance {instance_id} is not running (status={instance.status.value})"
            )

        instance.status = InstanceStatus.CANCELLED
        instance.completed_at = datetime.now(UTC)
        instance.error = f"Stopped: {reason}"
        await self.db.commit()

        await emit(
            AgentInstanceStopped(
                tenant_id=str(tenant_id),
                instance_id=str(instance_id),
                reason=reason,
            ),
            durable=True,
        )

        return instance

    async def _load_definition(self, definition_id: uuid.UUID) -> AgentDefinition | None:
        stmt = select(AgentDefinition).where(
            AgentDefinition.id == definition_id,
            AgentDefinition.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create_session(
        self,
        instance: AgentInstance,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID | None,
    ) -> AgentSession:
        if session_id:
            session = await self.db.get(AgentSession, session_id)
            if session and session.status == SessionStatus.ACTIVE:
                return session

        return AgentSession(
            tenant_id=tenant_id,
            instance_id=instance.id,
            status=SessionStatus.ACTIVE,
            messages=[],
        )

    async def _build_tool_executor(
        self,
        definition: AgentDefinition,
        tenant_id: uuid.UUID,
    ):
        """Build a tool executor function that resolves and invokes tools.

        Returns an async callable: (tool_name, arguments) → result
        """
        allowed_tools = set(definition.allowed_tools or [])

        async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
            if allowed_tools and tool_name not in allowed_tools:
                return {"error": f"Tool '{tool_name}' is not allowed for this agent"}

            try:
                from app.agents.tool_registry import tool_registry
                return await tool_registry.invoke(
                    tool_name=tool_name,
                    arguments=arguments,
                    tenant_id=tenant_id,
                )
            except Exception as exc:
                logger.warning(
                    "agent_tool_execution_failed",
                    tool_name=tool_name,
                    error=str(exc),
                )
                return {"error": f"Tool execution failed: {exc}"}

        return execute_tool

    async def _build_governance_checker(
        self,
        definition: AgentDefinition,
        tenant_id: uuid.UUID,
    ):
        """Build a governance checker that enforces policies before actions.

        Returns an async callable: (action, context) → None (raises on violation)
        """
        policy = definition.governance_policy or {}

        async def check_governance(action: str, context: dict[str, Any]) -> None:
            from app.agents.governance import GovernanceEngine
            engine = GovernanceEngine(policy)
            await engine.check(action=action, context=context, tenant_id=tenant_id)

        return check_governance
