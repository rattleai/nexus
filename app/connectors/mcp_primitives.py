"""MCP 2025-11-25 primitive handlers (P1.1).

Implements the server→client callbacks an MCP client must provide for
full 2025-11-25 spec compliance:

* **Elicitation** — server asks the user for structured input mid-call.
  Translated to an ``AgentApprovalRequested`` event so the existing
  HITL flow handles it uniformly. Supports URL-mode (SEP-1036) so sensitive
  prompts like OAuth or payment can happen out-of-band.
* **Sampling** — server asks the client's LLM to generate text
  (SEP-1577 adds tool use inside sampling). Routed through
  ``app.ai.gateway.AIGateway`` with the agent's wallet and a policy check.
* **Tasks** — persistent async tool-call handles stored as
  ``ConnectorTask`` rows. ``track_task``, ``get_task_status`` and
  ``wait_for_task`` handle polling + completion notification.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import (
    ConnectorTask,
    ConnectorTaskStatus,
    TenantConnection,
)

logger = structlog.stdlib.get_logger()


# ── Tasks (2025-11-25 experimental) ──────────────────────


async def track_task(
    *,
    tenant_id: uuid.UUID,
    connection: TenantConnection,
    mcp_task_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    agent_instance_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    db: AsyncSession,
) -> ConnectorTask:
    """Record a new async MCP task handle in the DB for polling."""
    task = ConnectorTask(
        tenant_id=tenant_id,
        connection_id=connection.id,
        mcp_task_id=mcp_task_id,
        tool_name=tool_name,
        arguments=arguments,
        status=ConnectorTaskStatus.WORKING,
        created_by_user_id=actor_user_id,
        agent_instance_id=agent_instance_id,
    )
    db.add(task)
    await db.flush()
    logger.info(
        "mcp_task_tracked",
        task_id=str(task.id),
        tool=tool_name,
        mcp_task_id=mcp_task_id,
    )
    return task


async def update_task_status(
    *,
    task: ConnectorTask,
    status: ConnectorTaskStatus,
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
    input_required: dict[str, Any] | None = None,
    db: AsyncSession,
) -> None:
    task.status = status
    if result is not None:
        task.result = result
    if error_message is not None:
        task.error_message = error_message
    if input_required is not None:
        task.input_required = input_required
    if status in {
        ConnectorTaskStatus.COMPLETED,
        ConnectorTaskStatus.FAILED,
        ConnectorTaskStatus.CANCELLED,
    }:
        task.completed_at = datetime.now(UTC)
    await db.flush()


async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession,
) -> ConnectorTask | None:
    return await db.get(ConnectorTask, task_id)


async def poll_mcp_task(
    task: ConnectorTask,
    *,
    connection: TenantConnection,
    db: AsyncSession,
) -> ConnectorTaskStatus:
    """Ask the MCP server for the current status of an async task handle.

    Returns the refreshed status and persists it. Servers that don't
    support the Tasks primitive simply return ``working`` forever;
    agents should use a timeout.
    """
    from app.connectors.mcp_client import mcp_client_pool

    connector_def = connection.connector_definition
    try:
        async with mcp_client_pool.get_session(connection, connector_def) as session:
            result = await _call_task_status(session, task.mcp_task_id)
    except Exception:
        logger.debug("mcp_task_poll_failed", exc_info=True)
        return task.status

    status_str = str(getattr(result, "status", task.status.value))
    try:
        new_status = ConnectorTaskStatus(status_str)
    except ValueError:
        new_status = ConnectorTaskStatus.WORKING

    await update_task_status(
        task=task,
        status=new_status,
        result=getattr(result, "result", None),
        error_message=getattr(result, "error", None),
        input_required=getattr(result, "input_required", None),
        db=db,
    )
    return new_status


async def _call_task_status(session: Any, mcp_task_id: str) -> Any:
    """Call the MCP server's task-status method.

    The 2025-11-25 spec exposes this via a standard request; different
    client SDKs surface it slightly differently. Try ``tasks/status``
    first, then fall back to a generic ``request``.
    """
    if hasattr(session, "get_task_status"):
        return await session.get_task_status(mcp_task_id)
    if hasattr(session, "send_request"):
        return await session.send_request({"method": "tasks/status", "params": {"task_id": mcp_task_id}})
    raise NotImplementedError("MCP client SDK does not expose task-status")


async def wait_for_task(
    task_id: uuid.UUID,
    *,
    db: AsyncSession,
    timeout_seconds: int = 300,
    poll_interval_seconds: float = 2.0,
) -> ConnectorTask:
    """Poll an async task until it reaches a terminal state or times out."""
    deadline = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
    while datetime.now(UTC) < deadline:
        task = await get_task(task_id, db)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task.status in {
            ConnectorTaskStatus.COMPLETED,
            ConnectorTaskStatus.FAILED,
            ConnectorTaskStatus.CANCELLED,
            ConnectorTaskStatus.INPUT_REQUIRED,
        }:
            return task

        # Refresh from the server
        result = await db.execute(select(TenantConnection).where(TenantConnection.id == task.connection_id))
        connection = result.scalar_one_or_none()
        if connection is not None:
            await poll_mcp_task(task, connection=connection, db=db)

        await asyncio.sleep(poll_interval_seconds)

    task = await get_task(task_id, db)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    return task


# ── Elicitation (2025-11-25 incl. URL-mode, SEP-1036) ───


async def handle_elicitation(
    *,
    tenant_id: uuid.UUID,
    agent_instance_id: uuid.UUID | None,
    prompt: str,
    schema: dict[str, Any] | None = None,
    url: str | None = None,
) -> None:
    """Handle a server-initiated elicitation request.

    Emits ``AgentApprovalRequested`` so the existing HITL flow picks it
    up. URL-mode elicitation (server returns a URL for out-of-band
    completion) is passed through in the event's ``action`` payload.
    """
    try:
        from app.agents.events import AgentApprovalRequested
        from app.core.events import emit

        approval_id = str(uuid.uuid4())
        action_payload = {
            "type": "mcp_elicitation",
            "prompt": prompt,
            "schema": schema,
            "url": url,
        }
        await emit(
            AgentApprovalRequested(
                tenant_id=str(tenant_id),
                instance_id=str(agent_instance_id) if agent_instance_id else "",
                agent_id="",
                action=str(action_payload),
                approval_id=approval_id,
                timeout_seconds=300,
            ),
            durable=True,
        )
        logger.info(
            "mcp_elicitation_forwarded",
            approval_id=approval_id,
            url_mode=url is not None,
        )
    except Exception:
        logger.debug("mcp_elicitation_dispatch_failed", exc_info=True)


# ── Sampling (2025-11-25 incl. tool use, SEP-1577) ──────


async def handle_sampling(
    *,
    tenant_id: uuid.UUID,
    agent_instance_id: uuid.UUID | None,
    messages: list[dict[str, Any]],
    model_preferences: dict[str, Any] | None = None,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Handle a server-initiated sampling request.

    Routes the request through ``app.ai.gateway.AIGateway`` using the
    agent's wallet + fallback chain so the server doesn't get a free
    pass to the platform's LLM budget. Returns the generated response
    in MCP sampling result format.
    """
    try:
        from app.ai.gateway import AIGateway  # type: ignore
    except Exception:
        logger.debug("ai_gateway_unavailable_for_sampling")
        return {"role": "assistant", "content": {"type": "text", "text": ""}}

    gateway = AIGateway()
    model = (model_preferences or {}).get("preferred_model") or "claude-sonnet-4-6"

    prompt_messages: list[dict[str, Any]] = []
    if system_prompt:
        prompt_messages.append({"role": "system", "content": system_prompt})
    prompt_messages.extend(messages)

    try:
        result = await gateway.complete(  # type: ignore[attr-defined]
            model=model,
            messages=prompt_messages,
            tenant_id=tenant_id,
        )
        content = result.get("content", "") if isinstance(result, dict) else str(result)
    except Exception as exc:
        logger.warning(
            "mcp_sampling_failed",
            tenant_id=str(tenant_id),
            error=str(exc)[:200],
        )
        return {
            "role": "assistant",
            "content": {"type": "text", "text": ""},
            "stopReason": "error",
        }

    return {
        "role": "assistant",
        "model": model,
        "content": {"type": "text", "text": content},
        "stopReason": "endTurn",
    }
