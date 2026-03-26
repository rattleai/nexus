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
        allowed_tools = set(definition.allowed_tools or [])
        db = self.db  # Capture in closure for tenant tool lookups

        async def execute_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
            if allowed_tools and tool_name not in allowed_tools:
                return {"error": f"Tool '{tool_name}' is not allowed for this agent"}

            try:
                from app.agents.tool_registry import tool_registry
                return await tool_registry.invoke(
                    tool_name=tool_name,
                    arguments=arguments,
                    tenant_id=tenant_id,
                    db=db,
                )
            except Exception as exc:
                logger.warning(
                    "agent_tool_execution_failed",
                    tool_name=tool_name,
                    error=str(exc),
                )
                return {"error": f"Tool execution failed: {exc}"}

        return execute_tool

    def _build_governance_checker(
        self,
        definition: AgentDefinition,
        tenant_id: uuid.UUID,
    ):
        """Build a governance checker that enforces policies before actions.

        Returns an async callable: (action, context) → None (raises on violation).
        Engine is created once and reused across all checks.
        """
        from app.agents.governance import GovernanceEngine

        policy = definition.governance_policy or {}
        engine = GovernanceEngine(policy)

        async def check_governance(action: str, context: dict[str, Any]) -> None:
            await engine.check(action=action, context=context, tenant_id=tenant_id)

        return check_governance

    # ── Data Source @ Mention Resolution ──────────────────────────────

    # Pattern: @[Display Name](ds:uuid) — injected by frontend source-mention-input
    _DS_MENTION_RE = re.compile(r"@\[([^\]]+)\]\(ds:([0-9a-f\-]{36})\)")

    async def _resolve_datasource_mentions(
        self,
        messages: list[dict[str, Any]],
        tenant_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Scan user messages for @[name](ds:uuid) patterns and inject source content.

        For each referenced data source:
        1. Load the DataSource record
        2. If extraction_result is cached, build a context summary
        3. If chunks exist, include the most relevant chunks
        4. Inject as a system message before the user message

        This gives agents focused access to exactly the data sources
        the user specified, similar to #file references in VS Code Copilot.
        """
        resolved: list[dict[str, Any]] = []

        for msg in messages:
            if msg.get("role") != "user" or not isinstance(msg.get("content"), str):
                resolved.append(msg)
                continue

            content = msg["content"]
            mentions = list(self._DS_MENTION_RE.finditer(content))

            if not mentions:
                resolved.append(msg)
                continue

            # Resolve each mentioned data source
            for match in mentions:
                ds_name = match.group(1)
                ds_id_str = match.group(2)

                try:
                    ds_id = uuid.UUID(ds_id_str)
                    context_text = await self._load_datasource_context(ds_id, tenant_id)
                    if context_text:
                        resolved.append({
                            "role": "system",
                            "content": (
                                f"=== Data Source: {ds_name} (id: {ds_id_str}) ===\n"
                                f"{context_text}\n"
                                f"=== End Data Source: {ds_name} ==="
                            ),
                        })
                except Exception:
                    logger.warning(
                        "datasource_mention_resolve_failed",
                        datasource_id=ds_id_str,
                        datasource_name=ds_name,
                        exc_info=True,
                    )

            # Clean the mention syntax from the user message for readability
            clean_content = self._DS_MENTION_RE.sub(r"@\1", content)
            resolved.append({**msg, "content": clean_content})

        return resolved

    async def _load_datasource_context(
        self,
        datasource_id: uuid.UUID,
        tenant_id: uuid.UUID,
        max_chunks: int = 20,
        max_chars: int = 15_000,
    ) -> str | None:
        """Load content from a data source for injection into agent context.

        Returns a text summary of the data source content, prioritizing:
        1. Extracted tables (most useful for configuration)
        2. Extracted sections
        3. Raw text chunks
        """
        try:
            from app.db.models.datasource import DataSource, DataSourceChunk, DataSourceStatus
        except ImportError:
            logger.debug("datasource_models_not_available")
            return None

        stmt = select(DataSource).where(
            DataSource.id == datasource_id,
            DataSource.tenant_id == tenant_id,
            DataSource.deleted_at.is_(None),
        )
        result = await self.db.execute(stmt)
        ds = result.scalar_one_or_none()
        if not ds:
            return None

        if ds.status != DataSourceStatus.READY:
            return f"[Data source '{ds.name}' is not ready (status: {ds.status})]"

        # Use cached extraction result if available
        if ds.extraction_result:
            return self._format_extraction_result(ds.extraction_result, max_chars)

        # Fall back to chunks
        chunk_stmt = (
            select(DataSourceChunk)
            .where(
                DataSourceChunk.data_source_id == datasource_id,
                DataSourceChunk.tenant_id == tenant_id,
            )
            .order_by(DataSourceChunk.chunk_index)
            .limit(max_chunks)
        )
        chunk_result = await self.db.execute(chunk_stmt)
        chunks = list(chunk_result.scalars().all())

        if not chunks:
            return None

        parts: list[str] = []
        total_chars = 0
        for chunk in chunks:
            if total_chars + len(chunk.content) > max_chars:
                parts.append(chunk.content[: max_chars - total_chars])
                break
            parts.append(chunk.content)
            total_chars += len(chunk.content)

        return "\n\n".join(parts)

    @staticmethod
    def _format_extraction_result(extraction: dict, max_chars: int = 15_000) -> str:
        """Format a cached ExtractionResult dict into agent-readable text."""
        parts: list[str] = []
        total = 0

        # Tables first (most valuable for configuration)
        tables = extraction.get("tables", [])
        if tables:
            parts.append(f"## Extracted Tables ({len(tables)} found)\n")
            for i, table in enumerate(tables):
                headers = table.get("headers", [])
                rows = table.get("rows", [])
                if not headers:
                    continue
                md = f"### Table {i + 1}\n"
                md += "| " + " | ".join(headers) + " |\n"
                md += "| " + " | ".join("---" for _ in headers) + " |\n"
                for row in rows[:50]:  # Cap at 50 rows per table
                    md += "| " + " | ".join(str(cell) for cell in row) + " |\n"
                if len(rows) > 50:
                    md += f"\n... ({len(rows) - 50} more rows)\n"
                parts.append(md)
                total += len(md)
                if total > max_chars:
                    break

        # Then sections
        sections = extraction.get("sections", [])
        if sections and total < max_chars:
            parts.append(f"\n## Extracted Sections ({len(sections)} found)\n")
            for section in sections:
                title = section.get("title", "Untitled")
                content = section.get("content", "")
                s = f"### {title}\n{content}\n"
                parts.append(s)
                total += len(s)
                if total > max_chars:
                    break

        # Raw text fallback
        if not parts:
            raw = extraction.get("raw_text", "")
            if raw:
                parts.append(raw[:max_chars])

        return "\n".join(parts)
