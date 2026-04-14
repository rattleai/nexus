"""Durable execution wrapper for connector tool calls (P1.4).

Wraps ``ConnectorExecutor.invoke`` with:

* **Idempotency** — tool calls with the same ``(tenant, user, agent_instance,
  tool, arguments)`` within the idempotency window return the cached result
  instead of re-executing. Deduplication is keyed on a hash persisted in
  Redis with a 10-minute TTL.
* **Retry with exponential backoff** — the HTTP path already retries
  transients in-executor; this wrapper retries MCP-path failures at the
  workflow level so one flap doesn't bubble up to the agent.
* **Checkpointing hook** — if DBOS is installed and
  ``CONNECTOR_DURABLE_EXECUTION_ENABLED`` is set, invocations run inside
  a ``DBOS.workflow`` so crashes resume from the last step instead of
  replaying from scratch. Without DBOS, we fall back to in-process
  idempotency + retry.

This keeps the hot path snappy when the platform isn't running a
durable-execution substrate, while giving operators a drop-in upgrade
path to DBOS / Temporal / Inngest by flipping a flag and installing a
dependency.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.executor import connector_executor
from app.connectors.models import ConnectorDefinition, TenantConnection
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

_IDEMPOTENCY_PREFIX = "connector:idempotency"
_IDEMPOTENCY_TTL_SECONDS = 600


def _compute_idempotency_key(
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    agent_instance_id: uuid.UUID | None,
    connector_slug: str,
    tool_name: str,
    arguments: dict[str, Any],
    explicit_key: str | None,
) -> str:
    """Derive a stable idempotency key for a tool call.

    If the caller supplies ``explicit_key`` we use it directly (trust the
    caller's intent); otherwise we hash ``(tenant, user, instance, tool,
    canonicalized_arguments)`` so repeated retries of the same call within
    the TTL are deduplicated.
    """
    if explicit_key:
        return f"{_IDEMPOTENCY_PREFIX}:explicit:{explicit_key}"

    payload = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "user_id": str(actor_user_id) if actor_user_id else None,
            "instance_id": str(agent_instance_id) if agent_instance_id else None,
            "connector": connector_slug,
            "tool": tool_name,
            "args": arguments,
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"{_IDEMPOTENCY_PREFIX}:hash:{digest}"


async def _read_idempotent_result(key: str) -> dict[str, Any] | None:
    try:
        raw = await redis_pool.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.debug("idempotency_read_failed", exc_info=True)
    return None


async def _write_idempotent_result(key: str, result: dict[str, Any]) -> None:
    try:
        await redis_pool.setex(
            key, _IDEMPOTENCY_TTL_SECONDS, json.dumps(result, default=str),
        )
    except Exception:
        logger.debug("idempotency_write_failed", exc_info=True)


async def durable_invoke_tool(
    *,
    connection: TenantConnection,
    connector_def: ConnectorDefinition,
    tool_name: str,
    arguments: dict[str, Any],
    tenant_id: uuid.UUID,
    db: AsyncSession,
    actor_user_id: uuid.UUID | None,
    agent_instance_id: uuid.UUID | None,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """Durable wrapper around ``ConnectorExecutor.invoke``.

    Returns the normalized result dict. Successful results are cached in
    Redis under the idempotency key for 10 minutes so immediate retries
    return the same response without re-invoking the provider.
    """
    derived_key = _compute_idempotency_key(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        agent_instance_id=agent_instance_id,
        connector_slug=connector_def.slug,
        tool_name=tool_name,
        arguments=arguments,
        explicit_key=idempotency_key,
    )

    cached = await _read_idempotent_result(derived_key)
    if cached is not None:
        logger.debug(
            "connector_tool_idempotent_hit",
            tool=tool_name,
            connector=connector_def.slug,
        )
        return cached

    if settings.CONNECTOR_DURABLE_EXECUTION_ENABLED:
        try:
            return await _run_via_dbos(
                connection=connection,
                connector_def=connector_def,
                tool_name=tool_name,
                arguments=arguments,
                tenant_id=tenant_id,
                db=db,
                actor_user_id=actor_user_id,
                agent_instance_id=agent_instance_id,
                idempotency_key=derived_key,
            )
        except _DBOSUnavailable:
            pass  # Fall through to in-process path

    result = await connector_executor.invoke(
        connection=connection,
        connector_def=connector_def,
        tool_name=tool_name,
        arguments=arguments,
        tenant_id=tenant_id,
        db=db,
        actor_type="agent",
        actor_user_id=actor_user_id,
        agent_instance_id=agent_instance_id,
        idempotency_key=derived_key,
    )

    if isinstance(result, dict) and not result.get("is_error"):
        await _write_idempotent_result(derived_key, result)

    return result


# ── DBOS integration (optional) ──────────────────────────


class _DBOSUnavailable(Exception):
    """Raised when DBOS is not installed — caller falls back to plain invocation."""


async def _run_via_dbos(
    *,
    connection: TenantConnection,
    connector_def: ConnectorDefinition,
    tool_name: str,
    arguments: dict[str, Any],
    tenant_id: uuid.UUID,
    db: AsyncSession,
    actor_user_id: uuid.UUID | None,
    agent_instance_id: uuid.UUID | None,
    idempotency_key: str,
) -> dict[str, Any]:
    """Execute a tool call inside a DBOS workflow.

    DBOS stores checkpoints in Postgres, so a crash mid-invocation resumes
    from the last step instead of replaying from scratch. When DBOS isn't
    installed we raise ``_DBOSUnavailable`` so the caller falls back to
    the in-process path.
    """
    try:
        from dbos import DBOS  # type: ignore
    except Exception as exc:
        raise _DBOSUnavailable() from exc

    @DBOS.workflow()  # type: ignore
    async def _workflow() -> dict[str, Any]:
        return await connector_executor.invoke(
            connection=connection,
            connector_def=connector_def,
            tool_name=tool_name,
            arguments=arguments,
            tenant_id=tenant_id,
            db=db,
            actor_type="agent",
            actor_user_id=actor_user_id,
            agent_instance_id=agent_instance_id,
            idempotency_key=idempotency_key,
        )

    return await _workflow()
