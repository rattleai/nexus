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

import asyncio
import re
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
from app.agents.governance import GovernanceViolationError
from app.agents.models import (
    AgentDefinition,
    AgentInstance,
    AgentSession,
    AgentStatus,
    InstanceStatus,
    SessionStatus,
)
from app.agents.runtime import AgentRuntime
from app.core.events import emit
from app.db.session import set_tenant_context

logger = structlog.stdlib.get_logger()

# Map runtime finish reasons to instance statuses
_FINISH_STATUS_MAP = {
    "completed": InstanceStatus.COMPLETED,
    "error": InstanceStatus.FAILED,
    "cancelled": InstanceStatus.CANCELLED,
    "max_steps": InstanceStatus.COMPLETED,
    "max_tokens": InstanceStatus.COMPLETED,
    "max_duration": InstanceStatus.FAILED,
}


class AgentExecutionError(Exception):
    """Raised when agent execution fails."""


def _sanitize_error(exc: Exception, max_len: int = 2000) -> str:
    """Sanitize error messages to prevent leaking sensitive data."""
    msg = str(exc)
    msg = re.sub(r'(sk-|pk_|Bearer\s+)\S+', '[REDACTED]', msg)
    msg = re.sub(r'AKIA[A-Z0-9]{16}', '[AWS_KEY_REDACTED]', msg)
    msg = re.sub(r'(postgresql|mysql|redis|mongodb)://\S+', '[DB_URL_REDACTED]', msg)
    msg = re.sub(r'(?i)(password|secret|token|key)\s*[=:]\s*\S+', r'\1=[REDACTED]', msg)
    msg = re.sub(r'(/Users/|/home/|/var/)\S+', '[PATH]', msg)
    return msg[:max_len]


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

        # Load definition (filtered by tenant_id for cross-tenant isolation)
        definition = await self._load_definition(definition_id, tenant_id)
        if not definition:
            raise AgentExecutionError(f"Agent definition {definition_id} not found")
        if definition.status != AgentStatus.ACTIVE:
            raise AgentExecutionError(f"Agent '{definition.name}' is not active (status={definition.status.value})")

        # Validate input_data structure
        messages = input_data.get("messages", [])
        if not messages and "prompt" in input_data:
            messages = [{"role": "user", "content": str(input_data["prompt"])}]
        if not messages:
            raise AgentExecutionError("input_data must contain 'messages' or 'prompt'")
        for msg in messages:
            if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                raise AgentExecutionError("Each message must have 'role' and 'content' keys")

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

        # Emit start event (best-effort — don't fail the run if event emission fails)
        try:
            await emit(
                AgentInstanceStarted(
                    tenant_id=str(tenant_id),
                    instance_id=str(instance.id),
                    agent_id=str(definition_id),
                    input_summary=str(input_data)[:200],
                ),
                durable=True,
            )
        except Exception:
            logger.warning("agent_start_event_failed", instance_id=str(instance.id), exc_info=True)

        # Include session history for context continuity
        if session.messages:
            messages = list(session.messages) + messages

        # Resolve @data_source mentions in user messages
        messages = await self._resolve_datasource_mentions(messages, tenant_id)

        # Set up tool executor and governance (created once, not per-call)
        tool_executor = self._build_tool_executor(definition, tenant_id)
        governance_checker = self._build_governance_checker(definition, tenant_id)

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

            # Map finish reason to status
            instance.status = _FINISH_STATUS_MAP.get(result.finish_reason, InstanceStatus.FAILED)
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
                        "content": f"[Tool: {step.tool_name}]",
                    })

            # Truncate to prevent unbounded JSONB growth
            from app.config import settings
            max_msgs = settings.AGENT_SESSION_MAX_MESSAGES
            if len(new_messages) > max_msgs:
                new_messages = new_messages[-max_msgs:]
            session.messages = new_messages

            await self.db.commit()

            # Emit completion event (best-effort — already committed)
            try:
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
            except Exception:
                logger.warning("agent_completion_event_failed", instance_id=str(instance.id), exc_info=True)

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
            # Rollback any uncommitted changes before writing failure state
            await self.db.rollback()

            # Re-fetch instance in clean transaction
            instance = await self.db.get(AgentInstance, instance.id)
            if instance:
                instance.status = InstanceStatus.FAILED
                instance.error = _sanitize_error(exc)
                instance.completed_at = datetime.now(UTC)

                # Structured error classification for better client UX
                if isinstance(exc, GovernanceViolationError):
                    instance.output_data = {
                        "error_code": "GOVERNANCE_VIOLATION",
                        "violation_type": exc.violation_type,
                        "details": exc.details,
                    }
                elif isinstance(exc, asyncio.TimeoutError):
                    instance.output_data = {"error_code": "TIMEOUT"}
                else:
                    instance.output_data = {"error_code": "EXECUTION_ERROR"}

                await self.db.commit()

            try:
                await emit(
                    AgentInstanceFailed(
                        tenant_id=str(tenant_id),
                        instance_id=str(instance.id) if instance else "unknown",
                        agent_id=str(definition_id),
                        error=_sanitize_error(exc, max_len=500),
                        step_number=instance.steps_executed if instance else 0,
                    ),
                    durable=True,
                )
            except Exception:
                logger.warning("agent_failure_event_failed", exc_info=True)

            logger.error(
                "agent_execution_failed",
                instance_id=str(instance.id) if instance else "unknown",
                agent_id=str(definition_id),
                error=_sanitize_error(exc),
                exc_info=True,
            )
            raise AgentExecutionError(_sanitize_error(exc)) from exc

        return instance

    async def stop(
        self,
        *,
        instance_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reason: str = "user_requested",
    ) -> AgentInstance:
        """Stop a running agent instance.

        Marks the instance as cancelled in the database. If the agent is
        executing in a Celery worker, the Celery task revocation mechanism
        should be used in conjunction with this method.
        """
        await set_tenant_context(self.db, str(tenant_id))

        # Use filtered query for tenant isolation instead of db.get()
        stmt = select(AgentInstance).where(
            AgentInstance.id == instance_id,
            AgentInstance.tenant_id == tenant_id,
        )
        result = await self.db.execute(stmt)
        instance = result.scalar_one_or_none()
        if not instance:
            raise AgentExecutionError(f"Instance {instance_id} not found")

        if instance.status not in (InstanceStatus.RUNNING, InstanceStatus.PENDING):
            raise AgentExecutionError(
                f"Instance {instance_id} is not running (status={instance.status.value})"
            )

        instance.status = InstanceStatus.CANCELLED
        instance.completed_at = datetime.now(UTC)
        instance.error = f"Stopped: {reason}"
        await self.db.commit()

        try:
            await emit(
                AgentInstanceStopped(
                    tenant_id=str(tenant_id),
                    instance_id=str(instance_id),
                    reason=reason,
                ),
                durable=True,
            )
        except Exception:
            logger.warning("agent_stop_event_failed", instance_id=str(instance_id), exc_info=True)

        return instance

    async def _load_definition(
        self, definition_id: uuid.UUID, tenant_id: uuid.UUID | None = None,
    ) -> AgentDefinition | None:
        conditions = [
            AgentDefinition.id == definition_id,
            AgentDefinition.deleted_at.is_(None),
        ]
        if tenant_id is not None:
            conditions.append(AgentDefinition.tenant_id == tenant_id)
        stmt = select(AgentDefinition).where(*conditions)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create_session(
        self,
        instance: AgentInstance,
        tenant_id: uuid.UUID,
        session_id: uuid.UUID | None,
    ) -> AgentSession:
        if session_id:
            # Use filtered query instead of db.get() for tenant isolation
            stmt = select(AgentSession).where(
                AgentSession.id == session_id,
                AgentSession.tenant_id == tenant_id,
            )
            result = await self.db.execute(stmt)
            session = result.scalar_one_or_none()
            if session and session.status == SessionStatus.ACTIVE:
                return session
            logger.warning(
                "agent_session_not_found_or_inactive",
                session_id=str(session_id),
                creating_new=True,
            )

        return AgentSession(
            tenant_id=tenant_id,
            instance_id=instance.id,
            status=SessionStatus.ACTIVE,
            messages=[],
        )

    def _build_tool_executor(
        self,
        definition: AgentDefinition,
        tenant_id: uuid.UUID,
    ):
        """Build a tool executor function that resolves and invokes tools.

        Returns an async callable: (tool_name, arguments) → result
        """
        from app.agents.setup import build_tool_executor

        return build_tool_executor(definition, tenant_id, self.db)

    def _build_governance_checker(
        self,
        definition: AgentDefinition,
        tenant_id: uuid.UUID,
    ):
        """Build a governance checker that enforces policies before actions.

        Returns an async callable: (action, context) → None (raises on violation).
        Engine is created once and reused across all checks.
        """
        from app.agents.setup import build_governance_checker

        return build_governance_checker(definition, tenant_id)

    # ── Data Source @ Mention Resolution ──────────────────────────────

    async def _resolve_datasource_mentions(
        self,
        messages: list[dict[str, Any]],
        tenant_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Scan user messages for @[name](ds:uuid) patterns and inject source content."""
        from app.agents.setup import resolve_datasource_mentions

        return await resolve_datasource_mentions(messages, tenant_id, self.db)
