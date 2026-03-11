"""Agent execution layer REST API.

Provides CRUD and execution endpoints for:
    - Agent definitions (blueprints)
    - Agent instances (running/completed)
    - Agent sessions
    - Agent memory
    - Workflows
    - Tenant tools
    - Agent policies
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.events import AgentDefinitionCreated, AgentDefinitionUpdated
from app.agents.models import (
    AgentDefinition,
    AgentInstance,
    AgentPolicy,
    AgentSession,
    AgentStatus,
    InstanceStatus,
    TenantTool,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
)
from app.agents.schemas import (
    AgentDefinitionCreate,
    AgentDefinitionResponse,
    AgentDefinitionUpdate,
    AgentInstanceCreate,
    AgentInstanceResponse,
    AgentPolicyCreate,
    AgentPolicyResponse,
    AgentSessionResponse,
    MemoryReadResponse,
    MemoryWriteRequest,
    PaginatedResponse,
    TenantToolCreate,
    TenantToolResponse,
    WorkflowDefinitionCreate,
    WorkflowDefinitionResponse,
    WorkflowRunCreate,
    WorkflowRunResponse,
)
from app.api.deps import RequireScopes, get_current_api_key, get_current_tenant, get_db
from app.core.events import emit
from app.db.models import ApiKey, Tenant
from app.db.session import set_tenant_context

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/agents")


# ── Agent Definitions ──────────────────────────────────────────────────


@router.post(
    "/definitions",
    response_model=AgentDefinitionResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("agents:write"))],
)
async def create_agent_definition(
    body: AgentDefinitionCreate,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent definition."""
    await set_tenant_context(db, str(tenant.id))

    agent = AgentDefinition(
        tenant_id=tenant.id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        system_prompt=body.system_prompt,
        model=body.model,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        allowed_tools=body.allowed_tools,
        max_steps_per_run=body.max_steps_per_run,
        max_duration_seconds=body.max_duration_seconds,
        max_tokens_per_run=body.max_tokens_per_run,
        sandbox_enabled=body.sandbox_enabled,
        memory_config=body.memory_config,
        governance_policy=body.governance_policy,
        metadata_=body.metadata,
    )
    db.add(agent)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, f"Agent with slug '{body.slug}' already exists")
    await db.refresh(agent)

    await emit(
        AgentDefinitionCreated(
            tenant_id=str(tenant.id),
            agent_id=str(agent.id),
            name=agent.name,
            slug=agent.slug,
        ),
        durable=True,
    )

    return agent


@router.get(
    "/definitions",
    response_model=PaginatedResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_agent_definitions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: AgentStatus | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List agent definitions for the current tenant."""
    await set_tenant_context(db, str(tenant.id))

    conditions = [
        AgentDefinition.tenant_id == tenant.id,
        AgentDefinition.deleted_at.is_(None),
    ]
    if status is not None:
        conditions.append(AgentDefinition.status == status)

    # Count total
    count_stmt = select(func.count()).select_from(AgentDefinition).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch page
    stmt = (
        select(AgentDefinition)
        .where(*conditions)
        .order_by(AgentDefinition.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=[AgentDefinitionResponse.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/definitions/{agent_id}",
    response_model=AgentDefinitionResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def get_agent_definition(
    agent_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific agent definition."""
    await set_tenant_context(db, str(tenant.id))
    agent = await _get_agent_or_404(db, agent_id, tenant.id)
    return agent


@router.put(
    "/definitions/{agent_id}",
    response_model=AgentDefinitionResponse,
    dependencies=[Depends(RequireScopes("agents:write"))],
)
async def update_agent_definition(
    agent_id: uuid.UUID,
    body: AgentDefinitionUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Update an agent definition."""
    await set_tenant_context(db, str(tenant.id))
    agent = await _get_agent_or_404(db, agent_id, tenant.id)

    changes = {}
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "metadata":
            setattr(agent, "metadata_", value)
        else:
            setattr(agent, field, value)
        changes[field] = value

    agent.version += 1
    await db.commit()
    await db.refresh(agent)

    await emit(
        AgentDefinitionUpdated(
            tenant_id=str(tenant.id),
            agent_id=str(agent.id),
            changes=changes,
        ),
        durable=True,
    )

    return agent


@router.delete(
    "/definitions/{agent_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("agents:admin"))],
)
async def delete_agent_definition(
    agent_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an agent definition."""
    from datetime import UTC, datetime

    await set_tenant_context(db, str(tenant.id))
    agent = await _get_agent_or_404(db, agent_id, tenant.id)
    agent.deleted_at = datetime.now(UTC)
    agent.status = AgentStatus.DISABLED
    await db.commit()


# ── Agent Instances ────────────────────────────────────────────────────


@router.post(
    "/definitions/{agent_id}/instances",
    response_model=AgentInstanceResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("agents:execute"))],
)
async def create_agent_instance(
    agent_id: uuid.UUID,
    body: AgentInstanceCreate,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Spawn a new agent instance (async execution via Celery)."""
    await set_tenant_context(db, str(tenant.id))
    agent = await _get_agent_or_404(db, agent_id, tenant.id)

    if agent.status != AgentStatus.ACTIVE:
        raise HTTPException(400, f"Agent '{agent.name}' is not active")

    # Check idempotency key for deduplication
    if body.idempotency_key:
        existing_stmt = select(AgentInstance).where(
            AgentInstance.tenant_id == tenant.id,
            AgentInstance.definition_id == agent.id,
            AgentInstance.idempotency_key == body.idempotency_key,
        )
        existing_result = await db.execute(existing_stmt)
        existing_instance = existing_result.scalar_one_or_none()
        if existing_instance:
            return existing_instance

    # Create instance record
    instance = AgentInstance(
        tenant_id=tenant.id,
        definition_id=agent.id,
        status=InstanceStatus.PENDING,
        input_data=body.input_data,
        idempotency_key=body.idempotency_key,
    )
    db.add(instance)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Race: another request with the same key was inserted concurrently
        existing_result = await db.execute(existing_stmt)
        existing_instance = existing_result.scalar_one_or_none()
        if existing_instance:
            return existing_instance
        raise HTTPException(409, "Duplicate idempotency key")
    await db.refresh(instance)

    # Dispatch to Celery for async execution
    from app.agents.tasks import execute_agent_run
    execute_agent_run.delay(
        definition_id=str(agent.id),
        tenant_id=str(tenant.id),
        input_data=body.input_data,
        api_key_id=str(api_key.id),  # Worker resolves key by ID — avoid passing hash through broker
        key_source="platform",
        session_id=str(body.session_id) if body.session_id else None,
    )

    return instance


@router.get(
    "/definitions/{agent_id}/instances",
    response_model=PaginatedResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_agent_instances(
    agent_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: InstanceStatus | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List instances of an agent definition."""
    await set_tenant_context(db, str(tenant.id))

    conditions = [
        AgentInstance.tenant_id == tenant.id,
        AgentInstance.definition_id == agent_id,
    ]
    if status is not None:
        conditions.append(AgentInstance.status == status)

    count_stmt = select(func.count()).select_from(AgentInstance).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(AgentInstance)
        .where(*conditions)
        .order_by(AgentInstance.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=[AgentInstanceResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/instances/{instance_id}",
    response_model=AgentInstanceResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def get_agent_instance(
    instance_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get agent instance details."""
    await set_tenant_context(db, str(tenant.id))
    instance = await db.get(AgentInstance, instance_id)
    if not instance or instance.tenant_id != tenant.id:
        raise HTTPException(404, "Instance not found")
    return instance


@router.post(
    "/instances/{instance_id}/stop",
    response_model=AgentInstanceResponse,
    dependencies=[Depends(RequireScopes("agents:execute"))],
)
async def stop_agent_instance(
    instance_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Stop a running agent instance."""
    from app.agents.executor import AgentExecutor
    await set_tenant_context(db, str(tenant.id))
    executor = AgentExecutor(db)
    instance = await executor.stop(
        instance_id=instance_id,
        tenant_id=tenant.id,
    )
    return instance


# ── Agent Sessions ─────────────────────────────────────────────────────


@router.get(
    "/instances/{instance_id}/sessions",
    response_model=PaginatedResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_agent_sessions(
    instance_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List sessions for an agent instance."""
    await set_tenant_context(db, str(tenant.id))
    conditions = [
        AgentSession.instance_id == instance_id,
        AgentSession.tenant_id == tenant.id,
    ]
    count_stmt = select(func.count()).select_from(AgentSession).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(AgentSession)
        .where(*conditions)
        .order_by(AgentSession.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=[AgentSessionResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


# ── Agent Memory ───────────────────────────────────────────────────────


@router.get(
    "/instances/{instance_id}/memory",
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def read_agent_memory(
    instance_id: uuid.UUID,
    namespace: str = "default",
    key: str | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Read agent memory entries."""
    from app.agents.memory import AgentMemoryManager
    await set_tenant_context(db, str(tenant.id))
    await _verify_instance_ownership(db, instance_id, tenant.id)
    memory = AgentMemoryManager(db)

    if key:
        value = await memory.get_long_term(instance_id, tenant.id, key, namespace)
        if value is None:
            raise HTTPException(404, "Memory entry not found")
        return {"namespace": namespace, "key": key, "value": value}
    else:
        entries = await memory.list_long_term(instance_id, tenant.id, namespace)
        return [
            {"namespace": e.namespace, "key": e.key, "value": e.value}
            for e in entries
        ]


@router.put(
    "/instances/{instance_id}/memory",
    dependencies=[Depends(RequireScopes("agents:write"))],
)
async def write_agent_memory(
    instance_id: uuid.UUID,
    body: MemoryWriteRequest,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Write an agent memory entry."""
    from app.agents.memory import AgentMemoryManager
    await set_tenant_context(db, str(tenant.id))
    await _verify_instance_ownership(db, instance_id, tenant.id)
    memory = AgentMemoryManager(db)

    entry = await memory.set_long_term(
        instance_id, tenant.id, body.key, body.value, namespace=body.namespace,
    )
    await db.commit()
    return {"namespace": entry.namespace, "key": entry.key, "value": entry.value}


@router.delete(
    "/instances/{instance_id}/memory",
    status_code=204,
    dependencies=[Depends(RequireScopes("agents:admin"))],
)
async def clear_agent_memory(
    instance_id: uuid.UUID,
    namespace: str | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Clear agent memory."""
    from app.agents.memory import AgentMemoryManager
    await set_tenant_context(db, str(tenant.id))
    await _verify_instance_ownership(db, instance_id, tenant.id)
    memory = AgentMemoryManager(db)
    await memory.clear_long_term(instance_id, tenant.id, namespace)
    await db.commit()


# ── Workflows ──────────────────────────────────────────────────────────


@router.post(
    "/workflows",
    response_model=WorkflowDefinitionResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("agents:write"))],
)
async def create_workflow(
    body: WorkflowDefinitionCreate,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a new workflow definition."""
    await set_tenant_context(db, str(tenant.id))

    workflow = WorkflowDefinition(
        tenant_id=tenant.id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        definition=body.definition,
        governance=body.governance,
        metadata_=body.metadata,
    )
    db.add(workflow)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, f"Workflow with slug '{body.slug}' already exists")
    await db.refresh(workflow)
    return workflow


@router.get(
    "/workflows",
    response_model=PaginatedResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List workflow definitions."""
    await set_tenant_context(db, str(tenant.id))

    conditions = [
        WorkflowDefinition.tenant_id == tenant.id,
        WorkflowDefinition.deleted_at.is_(None),
    ]
    count_stmt = select(func.count()).select_from(WorkflowDefinition).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(WorkflowDefinition)
        .where(*conditions)
        .order_by(WorkflowDefinition.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=[WorkflowDefinitionResponse.model_validate(w) for w in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post(
    "/workflows/{workflow_id}/run",
    response_model=WorkflowRunResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("agents:execute"))],
)
async def run_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowRunCreate,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Execute a workflow (async via Celery)."""
    await set_tenant_context(db, str(tenant.id))

    workflow = await db.get(WorkflowDefinition, workflow_id)
    if not workflow or workflow.tenant_id != tenant.id or workflow.deleted_at:
        raise HTTPException(404, "Workflow not found")
    if workflow.status != WorkflowStatus.ACTIVE:
        raise HTTPException(400, "Workflow is not active")

    # Create run record
    run = WorkflowRun(
        tenant_id=tenant.id,
        workflow_id=workflow_id,
        input_data=body.input_data,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Dispatch to Celery
    from app.agents.tasks import execute_workflow_run
    execute_workflow_run.delay(
        workflow_id=str(workflow_id),
        tenant_id=str(tenant.id),
        input_data=body.input_data,
        api_key_id=str(api_key.id),  # Worker resolves key by ID
    )

    return run


@router.get(
    "/workflows/{workflow_id}/runs",
    response_model=PaginatedResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_workflow_runs(
    workflow_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List runs for a workflow."""
    await set_tenant_context(db, str(tenant.id))
    conditions = [
        WorkflowRun.workflow_id == workflow_id,
        WorkflowRun.tenant_id == tenant.id,
    ]
    count_stmt = select(func.count()).select_from(WorkflowRun).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(WorkflowRun)
        .where(*conditions)
        .order_by(WorkflowRun.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=[WorkflowRunResponse.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


# ── Tenant Tools ───────────────────────────────────────────────────────


@router.post(
    "/tools",
    response_model=TenantToolResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("agents:admin"))],
)
async def register_tenant_tool(
    body: TenantToolCreate,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Register a custom tool for agents."""
    await set_tenant_context(db, str(tenant.id))

    # Encrypt sensitive auth_config fields before storage
    encrypted_auth_config = dict(body.auth_config) if body.auth_config else {}
    if encrypted_auth_config:
        from app.core.encryption import encrypt
        if encrypted_auth_config.get("type") == "bearer" and encrypted_auth_config.get("token"):
            encrypted_auth_config["token"] = encrypt(encrypted_auth_config["token"])
        elif encrypted_auth_config.get("type") == "api_key" and encrypted_auth_config.get("key"):
            encrypted_auth_config["key"] = encrypt(encrypted_auth_config["key"])

    tool = TenantTool(
        tenant_id=tenant.id,
        tool_name=body.tool_name,
        description=body.description,
        input_schema=body.input_schema,
        output_schema=body.output_schema,
        endpoint_url=body.endpoint_url,
        auth_config=encrypted_auth_config,
        health_check_url=body.health_check_url,
        metadata_=body.metadata,
    )
    db.add(tool)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, f"Tool '{body.tool_name}' already exists")
    await db.refresh(tool)
    return tool


@router.get(
    "/tools",
    response_model=list[TenantToolResponse],
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_tools(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all tools available to agents (built-in + custom)."""
    await set_tenant_context(db, str(tenant.id))
    from app.agents.tool_registry import tool_registry
    tenant_tools = await tool_registry.list_tenant_tools(tenant.id, db)
    return tenant_tools


@router.delete(
    "/tools/{tool_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("agents:admin"))],
)
async def remove_tenant_tool(
    tool_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Remove a custom tool."""
    from datetime import UTC, datetime
    await set_tenant_context(db, str(tenant.id))
    tool = await db.get(TenantTool, tool_id)
    if not tool or tool.tenant_id != tenant.id:
        raise HTTPException(404, "Tool not found")
    tool.deleted_at = datetime.now(UTC)
    tool.is_active = False
    await db.commit()


# ── Agent Policies ─────────────────────────────────────────────────────


@router.post(
    "/policies",
    response_model=AgentPolicyResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("agents:admin"))],
)
async def create_agent_policy(
    body: AgentPolicyCreate,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Create a reusable governance policy."""
    await set_tenant_context(db, str(tenant.id))

    policy = AgentPolicy(
        tenant_id=tenant.id,
        name=body.name,
        description=body.description,
        max_spend_per_run_usd=body.max_spend_per_run_usd,
        max_spend_per_day_usd=body.max_spend_per_day_usd,
        max_spend_per_month_usd=body.max_spend_per_month_usd,
        allowed_tools=body.allowed_tools,
        denied_tools=body.denied_tools,
        require_approval_for=body.require_approval_for,
        approval_timeout_seconds=body.approval_timeout_seconds,
        approval_default_action=body.approval_default_action,
        max_requests_per_minute=body.max_requests_per_minute,
        max_steps_per_run=body.max_steps_per_run,
        rules=body.rules,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy


@router.get(
    "/policies",
    response_model=PaginatedResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_agent_policies(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List governance policies."""
    await set_tenant_context(db, str(tenant.id))
    conditions = [AgentPolicy.tenant_id == tenant.id]
    count_stmt = select(func.count()).select_from(AgentPolicy).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(AgentPolicy)
        .where(*conditions)
        .order_by(AgentPolicy.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=[AgentPolicyResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


# ── Helpers ────────────────────────────────────────────────────────────


async def _get_agent_or_404(
    db: AsyncSession,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> AgentDefinition:
    agent = await db.get(AgentDefinition, agent_id)
    if not agent or agent.tenant_id != tenant_id or agent.deleted_at:
        raise HTTPException(404, "Agent definition not found")
    return agent


async def _verify_instance_ownership(
    db: AsyncSession,
    instance_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> None:
    """Verify the instance belongs to the tenant, raise 404 otherwise."""
    instance = await db.get(AgentInstance, instance_id)
    if not instance or instance.tenant_id != tenant_id:
        raise HTTPException(404, "Instance not found")
