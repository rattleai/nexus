"""MCP tools for agent operations.

Exposes agent CRUD, execution, monitoring, and approval operations
via the Model Context Protocol, allowing external AI agents to
orchestrate the platform's own agent system.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.stdlib.get_logger()


async def agent_list(
    *, tenant: Any, db: AsyncSession, status: str | None = None,
) -> dict:
    """List agent definitions for the tenant."""
    from app.agents.models import AgentDefinition, AgentStatus
    from app.db.session import set_tenant_context

    await set_tenant_context(db, str(tenant.id))

    conditions = [
        AgentDefinition.tenant_id == tenant.id,
        AgentDefinition.deleted_at.is_(None),
    ]
    if status:
        conditions.append(AgentDefinition.status == AgentStatus(status))

    result = await db.execute(
        select(AgentDefinition).where(*conditions).order_by(AgentDefinition.created_at.desc()).limit(50)
    )
    agents = result.scalars().all()

    return {
        "agents": [
            {
                "id": str(a.id),
                "name": a.name,
                "slug": a.slug,
                "status": a.status.value,
                "model": a.model,
                "description": a.description[:200] if a.description else "",
            }
            for a in agents
        ],
        "count": len(agents),
    }


async def agent_get(
    *, tenant: Any, db: AsyncSession, agent_id: str,
) -> dict:
    """Get details of a specific agent definition."""
    import uuid
    from app.agents.models import AgentDefinition
    from app.db.session import set_tenant_context

    await set_tenant_context(db, str(tenant.id))

    agent = await db.get(AgentDefinition, uuid.UUID(agent_id))
    if not agent or agent.tenant_id != tenant.id or agent.deleted_at:
        return {"error": "Agent not found"}

    return {
        "id": str(agent.id),
        "name": agent.name,
        "slug": agent.slug,
        "status": agent.status.value,
        "model": agent.model,
        "description": agent.description,
        "system_prompt": agent.system_prompt[:500] if agent.system_prompt else "",
        "allowed_tools": agent.allowed_tools,
        "max_steps_per_run": agent.max_steps_per_run,
        "max_duration_seconds": agent.max_duration_seconds,
        "sandbox_enabled": agent.sandbox_enabled,
    }


async def agent_run(
    *, tenant: Any, db: AsyncSession,
    agent_id: str, input_messages: list[dict] | None = None,
    api_key: str = "", key_source: str = "mcp",
) -> dict:
    """Execute an agent and return the result."""
    import uuid
    from app.agents.executor import AgentExecutor
    from app.db.session import set_tenant_context

    await set_tenant_context(db, str(tenant.id))

    # Use the caller's actual API key (not hardcoded "platform") so that
    # billing, audit trails, and scope enforcement apply correctly.
    effective_key = api_key or "platform"
    effective_source = key_source or "mcp"

    # Entitlement check
    from app.billing.entitlements import entitlements, EntitlementDenied
    try:
        await entitlements.require_feature(tenant.id, "agents:execute", db=db)
    except EntitlementDenied as exc:
        return {"error": str(exc)}

    # Audit event
    from app.core.audit import AuditAction, emit_audit_event
    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="agent_run",
        resource_id=agent_id,
        tenant_id=tenant.id,
        metadata={"source": "mcp", "key_source": effective_source},
    )

    # Validate input_messages size to prevent abuse via massive LLM calls
    messages = input_messages or []
    _MAX_MESSAGES = 50
    _MAX_CONTENT_LEN = 32_768
    if len(messages) > _MAX_MESSAGES:
        return {"error": f"Too many messages (max {_MAX_MESSAGES})"}
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > _MAX_CONTENT_LEN:
            return {"error": f"Message content too long (max {_MAX_CONTENT_LEN} chars)"}

    executor = AgentExecutor(db)
    try:
        instance = await executor.run(
            definition_id=uuid.UUID(agent_id),
            tenant_id=tenant.id,
            input_data={"messages": messages},
            api_key=effective_key,
            key_source=effective_source,
        )
        return {
            "instance_id": str(instance.id),
            "status": instance.status.value,
            "output": instance.output_data,
            "steps_executed": instance.steps_executed,
            "tokens_used": instance.tokens_used,
            "cost_usd": instance.cost_usd,
        }
    except Exception as exc:
        return {"error": str(exc)[:500]}


async def agent_instances(
    *, tenant: Any, db: AsyncSession,
    agent_id: str | None = None, status: str | None = None,
) -> dict:
    """List agent instances, optionally filtered by agent or status."""
    import uuid
    from app.agents.models import AgentInstance, InstanceStatus
    from app.db.session import set_tenant_context

    await set_tenant_context(db, str(tenant.id))

    conditions = [AgentInstance.tenant_id == tenant.id]
    if agent_id:
        conditions.append(AgentInstance.definition_id == uuid.UUID(agent_id))
    if status:
        conditions.append(AgentInstance.status == InstanceStatus(status))

    result = await db.execute(
        select(AgentInstance).where(*conditions).order_by(AgentInstance.created_at.desc()).limit(50)
    )
    instances = result.scalars().all()

    return {
        "instances": [
            {
                "id": str(i.id),
                "definition_id": str(i.definition_id),
                "status": i.status.value,
                "steps_executed": i.steps_executed,
                "tokens_used": i.tokens_used,
                "cost_usd": i.cost_usd,
            }
            for i in instances
        ],
        "count": len(instances),
    }


async def agent_approvals(*, tenant: Any, db: AsyncSession) -> dict:
    """List pending approval requests for the tenant."""
    from app.agents.governance import GovernanceEngine
    approvals = await GovernanceEngine.list_pending_approvals(tenant.id)
    return {"approvals": approvals, "count": len(approvals)}


async def agent_approve(
    *, tenant: Any, db: AsyncSession,
    approval_id: str, decision: str,
) -> dict:
    """Resolve an approval request (approve or deny)."""
    import json
    from app.agents.governance import GovernanceEngine
    from app.core.redis import redis_pool

    if decision not in ("approved", "denied"):
        return {"error": "decision must be 'approved' or 'denied'"}

    # Verify tenant ownership BEFORE resolving to prevent cross-tenant
    # approval resolution.
    approval_key = f"agent:gov:approval:{approval_id}"
    raw = await redis_pool.get(approval_key)
    if not raw:
        return {"error": "Approval not found or expired"}
    approval_data = json.loads(raw)
    if approval_data.get("tenant_id") != str(tenant.id):
        return {"error": "Approval not found or expired"}

    result = await GovernanceEngine.resolve_approval(
        approval_id=approval_id,
        decision=decision,
        resolved_by=f"mcp:{tenant.id}",
    )

    if result is None:
        return {"error": "Approval not found or expired"}
    return result
