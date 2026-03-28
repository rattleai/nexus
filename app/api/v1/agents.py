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
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.events import (
    AgentDefinitionCreated,
    AgentDefinitionUpdated,
    ConversationStarted,
    ConversationTurnCompleted,
    ConversationEnded,
)
from app.agents.models import (
    AgentDefinition,
    AgentInstance,
    AgentPolicy,
    AgentSession,
    AgentStatus,
    InstanceStatus,
    SessionStatus,
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
    CapabilityPresetCreate,
    CapabilityResolveRequest,
    ConversationReplyRequest,
    ConversationSessionResponse,
    ConversationStartRequest,
    MemoryWriteRequest,
    PaginatedResponse,
    TenantToolCreate,
    TenantToolResponse,
    WorkflowDefinitionCreate,
    WorkflowDefinitionResponse,
    WorkflowRunCreate,
    WorkflowRunResponse,
)
from app.api.deps import RequireScopes, get_current_api_key, get_current_api_key_optional, get_current_tenant, get_db
from app.core.events import emit
from app.db.models import ApiKey, Tenant
from app.db.session import set_tenant_context

logger = structlog.stdlib.get_logger()

# Sensitive field names in auth_config that must be encrypted/masked
_AUTH_SENSITIVE_KEYS = {"token", "key", "secret", "password", "client_secret", "api_key"}

router = APIRouter(prefix="/agents")


async def _enforce_concurrent_limit(
    db: AsyncSession, agent: AgentDefinition, tenant_id: uuid.UUID,
) -> None:
    """Atomically enforce max_concurrent_instances via row-level lock.

    Acquires a FOR UPDATE lock on the AgentDefinition row so that
    concurrent requests serialize their count-then-insert sequence,
    preventing TOCTOU races that could exceed the limit.
    """
    if agent.max_concurrent_instances <= 0:
        return
    # Lock the definition row — concurrent callers block here until we commit
    await db.execute(
        select(AgentDefinition).where(AgentDefinition.id == agent.id).with_for_update()
    )
    active_count_stmt = select(func.count()).select_from(AgentInstance).where(
        AgentInstance.tenant_id == tenant_id,
        AgentInstance.definition_id == agent.id,
        AgentInstance.status.in_([InstanceStatus.PENDING, InstanceStatus.RUNNING]),
    )
    active_count = (await db.execute(active_count_stmt)).scalar() or 0
    if active_count >= agent.max_concurrent_instances:
        raise HTTPException(
            429,
            f"Agent '{agent.name}' has reached its concurrent instance limit "
            f"({agent.max_concurrent_instances}). Wait for running instances to complete.",
        )


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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent definition."""
    await set_tenant_context(db, str(tenant.id))

    # Resolve capabilities from preset if provided
    capabilities = body.capabilities
    if body.capability_preset_id and not capabilities:
        from app.agents.models import CapabilityPreset
        from sqlalchemy import or_
        preset_stmt = select(CapabilityPreset).where(
            CapabilityPreset.id == body.capability_preset_id,
            CapabilityPreset.deleted_at.is_(None),
            or_(
                CapabilityPreset.tenant_id == tenant.id,
                CapabilityPreset.tenant_id.is_(None),
            ),
        )
        preset_result = await db.execute(preset_stmt)
        preset = preset_result.scalar_one_or_none()
        if preset:
            capabilities = preset.capabilities
            if preset.additional_tools:
                body.allowed_tools = list(set(body.allowed_tools) | set(preset.additional_tools))
            if preset.governance_overrides:
                body.governance_policy = {**body.governance_policy, **preset.governance_overrides}

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
        capabilities=capabilities,
        max_steps_per_run=body.max_steps_per_run,
        max_duration_seconds=body.max_duration_seconds,
        max_tokens_per_run=body.max_tokens_per_run,
        sandbox_enabled=body.sandbox_enabled,
        parallel_tool_execution=body.parallel_tool_execution,
        max_concurrent_instances=body.max_concurrent_instances,
        memory_config=body.memory_config,
        governance_policy=body.governance_policy,
        metadata_=body.metadata,
    )
    db.add(agent)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Agent with slug '{body.slug}' already exists") from exc
    await db.refresh(agent)
    await db.commit()

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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Update an agent definition."""
    await set_tenant_context(db, str(tenant.id))
    agent = await _get_agent_or_404(db, agent_id, tenant.id)

    # Optimistic concurrency control
    if body.expected_version is not None and agent.version != body.expected_version:
        raise HTTPException(409, "Agent was modified concurrently. Refresh and retry.")

    # Allowlist of mutable fields to prevent mass-assignment of sensitive columns
    _MUTABLE_FIELDS = {
        "name", "slug", "description", "status", "system_prompt", "model",
        "temperature", "max_tokens", "allowed_tools", "capabilities", "tool_versions",
        "max_steps_per_run", "max_duration_seconds", "max_tokens_per_run",
        "sandbox_enabled", "parallel_tool_execution", "max_concurrent_instances",
        "memory_config", "output_schema", "governance_policy", "metadata",
    }
    changes = {}
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "expected_version":
            continue
        if field not in _MUTABLE_FIELDS:
            continue
        if field == "metadata":
            agent.metadata_ = value  # type: ignore[assignment]
        else:
            setattr(agent, field, value)
        changes[field] = value

    agent.version += 1
    await db.flush()
    await db.refresh(agent)
    await db.commit()

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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an agent definition."""
    from datetime import UTC, datetime

    await set_tenant_context(db, str(tenant.id))
    agent = await _get_agent_or_404(db, agent_id, tenant.id)
    agent.deleted_at = datetime.now(UTC)
    agent.status = AgentStatus.DISABLED
    await db.commit()


# ── Capability Catalog & Presets ───────────────────────────────────────


@router.get("/capabilities")
async def get_capability_catalog(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Return the full capability catalog (platform + all plugins).

    No database hit — derived from in-memory plugin registry.
    """
    from app.agents.capabilities import capability_resolver
    from app.agents.schemas import (
        CapabilityCatalogResponse,
        CapabilityDomainResponse,
        ToolCapabilityResponse,
    )

    domains = capability_resolver.get_catalog()
    return CapabilityCatalogResponse(
        domains=[
            CapabilityDomainResponse(
                slug=d.slug,
                label=d.label,
                icon=d.icon,
                capabilities=[
                    ToolCapabilityResponse(
                        slug=c.slug,
                        label=c.label,
                        description=c.description,
                        tools=list(c.tools),
                        tool_count=len(c.tools),
                        risk_level=c.risk_level,
                        requires_approval_default=c.requires_approval_default,
                    )
                    for c in d.capabilities
                ],
            )
            for d in domains
        ],
    )


@router.post("/capabilities/resolve")
async def resolve_capabilities(
    body: "CapabilityResolveRequest",
    tenant: Tenant = Depends(get_current_tenant),
):
    """Preview which tools a set of capabilities resolves to."""
    from app.agents.capabilities import capability_resolver
    from app.agents.schemas import CapabilityResolveRequest, CapabilityResolveResponse

    tools = sorted(capability_resolver.resolve(body.capabilities))
    return CapabilityResolveResponse(tools=tools, count=len(tools))


@router.get(
    "/capability-presets",
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_capability_presets(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List capability presets (system + tenant-scoped)."""
    from app.agents.models import CapabilityPreset
    from app.agents.schemas import CapabilityPresetResponse

    await set_tenant_context(db, str(tenant.id))
    stmt = select(CapabilityPreset).where(
        CapabilityPreset.deleted_at.is_(None),
        (CapabilityPreset.tenant_id == tenant.id) | (CapabilityPreset.tenant_id.is_(None)),
    ).order_by(CapabilityPreset.is_system.desc(), CapabilityPreset.name)
    result = await db.execute(stmt)
    presets = result.scalars().all()
    return [CapabilityPresetResponse.model_validate(p) for p in presets]


@router.post(
    "/capability-presets",
    status_code=201,
    dependencies=[Depends(RequireScopes("agents:write"))],
)
async def create_capability_preset(
    body: "CapabilityPresetCreate",
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a tenant-scoped capability preset."""
    from app.agents.models import CapabilityPreset
    from app.agents.schemas import CapabilityPresetCreate, CapabilityPresetResponse

    await set_tenant_context(db, str(tenant.id))
    preset = CapabilityPreset(
        tenant_id=tenant.id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        icon=body.icon,
        capabilities=body.capabilities,
        additional_tools=body.additional_tools,
        governance_overrides=body.governance_overrides,
    )
    db.add(preset)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Preset with slug '{body.slug}' already exists") from exc
    await db.refresh(preset)
    await db.commit()
    return CapabilityPresetResponse.model_validate(preset)


@router.put(
    "/capability-presets/{preset_id}",
    dependencies=[Depends(RequireScopes("agents:write"))],
)
async def update_capability_preset(
    preset_id: uuid.UUID,
    body: CapabilityPresetCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update a tenant-scoped capability preset (system presets cannot be modified)."""
    from app.agents.models import CapabilityPreset
    from app.agents.schemas import CapabilityPresetResponse

    await set_tenant_context(db, str(tenant.id))
    stmt = select(CapabilityPreset).where(
        CapabilityPreset.id == preset_id,
        CapabilityPreset.tenant_id == tenant.id,
        CapabilityPreset.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(404, "Preset not found")
    if preset.is_system:
        raise HTTPException(403, "System presets cannot be modified")
    preset.name = body.name
    preset.slug = body.slug
    preset.description = body.description
    preset.icon = body.icon
    preset.capabilities = body.capabilities
    preset.additional_tools = body.additional_tools
    preset.governance_overrides = body.governance_overrides
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Preset with slug '{body.slug}' already exists") from exc
    await db.commit()
    return CapabilityPresetResponse.model_validate(preset)


@router.delete(
    "/capability-presets/{preset_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("agents:write"))],
)
async def delete_capability_preset(
    preset_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete a tenant-scoped capability preset (system presets cannot be deleted)."""
    from datetime import UTC, datetime

    from app.agents.models import CapabilityPreset

    await set_tenant_context(db, str(tenant.id))
    stmt = select(CapabilityPreset).where(
        CapabilityPreset.id == preset_id,
        CapabilityPreset.tenant_id == tenant.id,
        CapabilityPreset.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(404, "Preset not found")
    if preset.is_system:
        raise HTTPException(403, "System presets cannot be deleted")
    preset.deleted_at = datetime.now(UTC)
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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Spawn a new agent instance (async execution via Celery)."""
    await set_tenant_context(db, str(tenant.id))

    from app.billing.entitlements import entitlements, EntitlementDenied
    try:
        await entitlements.require_feature(tenant.id, "agents:execute", db=db)
    except EntitlementDenied:
        raise HTTPException(403, "Feature not available on your current plan") from None

    agent = await _get_agent_or_404(db, agent_id, tenant.id)

    if agent.status != AgentStatus.ACTIVE:
        raise HTTPException(400, f"Agent '{agent.name}' is not active")

    # Enforce max concurrent instances (serialized via row-level lock)
    await _enforce_concurrent_limit(db, agent, tenant.id)

    # Check idempotency key for deduplication
    existing_stmt = None  # Initialize to prevent NameError in except block
    if body.idempotency_key:
        existing_stmt = select(AgentInstance).where(
            AgentInstance.tenant_id == tenant.id,
            AgentInstance.definition_id == agent.id,
            AgentInstance.idempotency_key == body.idempotency_key,
        )
        existing_result = await db.execute(existing_stmt)
        existing_instance = existing_result.scalar_one_or_none()
        if existing_instance:
            if existing_instance.status == InstanceStatus.FAILED:
                raise HTTPException(
                    409,
                    "Previous execution with this idempotency key failed. "
                    "Use a new key to retry.",
                )
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
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # Only handle idempotency-key conflicts; re-raise other constraint violations
        if "uq_agent_instance_idempotency" in str(getattr(exc, "orig", "")) and existing_stmt is not None:
            existing_result = await db.execute(existing_stmt)
            existing_instance = existing_result.scalar_one_or_none()
            if existing_instance:
                return existing_instance
        raise HTTPException(409, "Duplicate or constraint violation") from exc
    await db.refresh(instance)
    await db.commit()

    # Dispatch to Celery for async execution.
    # Use instance.id as the Celery task_id so stop_agent_instance can revoke it.
    from app.agents.tasks import execute_agent_run
    execute_agent_run.apply_async(
        kwargs={
            "definition_id": str(agent.id),
            "tenant_id": str(tenant.id),
            "input_data": body.input_data,
            "api_key_id": str(api_key.id) if api_key else None,  # Worker resolves key by ID
            "key_source": "platform",
            "session_id": str(body.session_id) if body.session_id else None,
        },
        task_id=str(instance.id),
    )

    return instance


@router.get(
    "/instances",
    response_model=PaginatedResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_all_instances(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="Comma-separated statuses, e.g. 'running,pending'"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List agent instances across all definitions for this tenant.

    Supports comma-separated status filtering for the instance monitor bar,
    e.g. ``?status=running,pending`` to fetch all active instances.
    """
    await set_tenant_context(db, str(tenant.id))

    conditions = [AgentInstance.tenant_id == tenant.id]
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        conditions.append(AgentInstance.status.in_(statuses))

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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
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

    # Revoke the Celery task to stop worker-side execution
    try:
        from app.workers.celery_app import celery_app
        celery_app.control.revoke(str(instance_id), terminate=True, signal="SIGTERM")
    except Exception:
        logger.warning("celery_revoke_failed", instance_id=str(instance_id), exc_info=True)

    return instance


# ── Agent Definition Streaming (ReAct Loop SSE) ──────────────────────────


@router.post(
    "/definitions/{agent_id}/run-stream",
    dependencies=[Depends(RequireScopes("agents:execute"))],
)
async def run_agent_stream(
    agent_id: uuid.UUID,
    body: AgentInstanceCreate,
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Run an agent definition with streaming SSE output.

    Streams step-by-step ReAct loop events (thinking, tool_call, tool_result,
    content_delta, step_completed, run_completed) in real-time.
    """
    from starlette.responses import StreamingResponse

    from app.agents.runtime import AgentRuntime

    await set_tenant_context(db, str(tenant.id))

    from app.billing.entitlements import entitlements, EntitlementDenied
    try:
        await entitlements.require_feature(tenant.id, "agents:execute", db=db)
    except EntitlementDenied:
        raise HTTPException(403, "Feature not available on your current plan") from None

    agent = await _get_agent_or_404(db, agent_id, tenant.id)

    if agent.status != AgentStatus.ACTIVE:
        raise HTTPException(400, f"Agent '{agent.name}' is not active")

    # Enforce max concurrent instances (serialized via row-level lock)
    await _enforce_concurrent_limit(db, agent, tenant.id)

    # Resolve API key for the runtime
    from app.core.encryption import decrypt
    from sqlalchemy import select as _select
    from app.db.models.ai import TenantAIProviderKey

    # Use platform key resolution
    provider_key_result = await db.execute(
        _select(TenantAIProviderKey).where(
            TenantAIProviderKey.tenant_id == tenant.id,
            TenantAIProviderKey.is_active.is_(True),
        ).limit(1)
    )
    provider_key = provider_key_result.scalar_one_or_none()
    resolved_api_key = decrypt(provider_key.encrypted_api_key) if provider_key else ""

    if not resolved_api_key:
        raise HTTPException(503, "No AI provider key configured for this tenant")

    runtime = AgentRuntime(
        definition=agent,
        tenant_id=tenant.id,
        api_key=resolved_api_key,
        key_source="platform",
    )

    from datetime import UTC, datetime as _dt

    instance_id = uuid.uuid4()

    # Create agent instance record for audit trail
    instance = AgentInstance(
        id=instance_id,
        tenant_id=tenant.id,
        definition_id=agent.id,
        status=InstanceStatus.RUNNING,
        input_data=body.input_data,
    )
    db.add(instance)
    await db.flush()
    await db.refresh(instance)
    await db.commit()

    # Re-establish RLS context: SET LOCAL is transaction-scoped and the
    # commit above ended the transaction, wiping app.tenant_id.
    await set_tenant_context(db, str(tenant.id))

    messages = body.input_data.get("messages", [{"role": "user", "content": str(body.input_data)}])

    # Build tool executor and governance checker so agents can actually
    # invoke tools (CPQ, built-in, tenant-custom) during the streaming run.
    from app.agents.setup import build_tool_executor, build_governance_checker, resolve_datasource_mentions

    tool_executor = build_tool_executor(agent, tenant.id, db)
    governance_checker = build_governance_checker(agent, tenant.id)

    # Resolve @[name](ds:uuid) data source mentions in user messages
    messages = await resolve_datasource_mentions(messages, tenant.id, db)

    async def event_generator():
        import json as _json

        _completed_normally = False
        _final_data: dict = {}

        # Emit instance_id as first SSE event so frontend can navigate immediately
        yield f"event: run_started\ndata: {_json.dumps({'instance_id': str(instance_id), 'definition_id': str(agent.id)})}\n\n"

        try:
            async for event in runtime.run_stream(
                messages=messages,
                instance_id=instance_id,
                tool_executor=tool_executor,
                governance_checker=governance_checker,
                db=db,
            ):
                # Check client disconnect
                if await request.is_disconnected():
                    runtime.cancel()
                    return

                event_type = event.get("event", "message")
                event_data = event.get("data", {})

                # Track successful completion so the finally block can set COMPLETED
                if event_type == "run_completed":
                    _completed_normally = True
                    _final_data = event_data

                yield f"event: {event_type}\ndata: {_json.dumps(event_data, default=str)}\n\n"
        except Exception as exc:
            import json as _json2
            logger.error("agent_stream_error", error=str(exc), exc_info=True)
            yield f"event: error\ndata: {_json2.dumps({'message': 'An internal error occurred. Please try again.'})}\n\n"
        finally:
            # Immediate cleanup — don't rely on periodic sweep to catch orphaned instances
            async def _cleanup_instance() -> None:
                """Update instance status, recovering from PendingRollbackError if needed."""
                from sqlalchemy.exc import PendingRollbackError

                try:
                    await set_tenant_context(db, str(tenant.id))
                    inst = await db.get(AgentInstance, instance_id)
                except PendingRollbackError:
                    await db.rollback()
                    await set_tenant_context(db, str(tenant.id))
                    inst = await db.get(AgentInstance, instance_id)

                if inst and inst.status in (InstanceStatus.RUNNING, InstanceStatus.PENDING):
                    if _completed_normally:
                        inst.status = InstanceStatus.COMPLETED
                        inst.output_data = _final_data.get("output", {})
                        inst.tokens_used = _final_data.get("total_tokens", 0)
                        inst.cost_usd = _final_data.get("total_cost_usd", 0)
                        inst.steps_executed = _final_data.get("steps", 0)
                    elif runtime._cancelled:
                        inst.status = InstanceStatus.CANCELLED
                    else:
                        inst.status = InstanceStatus.FAILED
                        inst.error = "Stream terminated unexpectedly"
                    inst.completed_at = _dt.now(UTC)
                    await db.commit()

            try:
                await _cleanup_instance()
            except Exception:
                logger.warning("stream_instance_cleanup_failed", instance_id=str(instance_id), exc_info=True)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Instance-Id": str(instance_id),
            "Access-Control-Expose-Headers": "X-Instance-Id",
        },
    )


# ── Agent Instance Streaming (SSE) ──────────────────────────────────────


@router.get(
    "/instances/{instance_id}/stream",
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def stream_agent_instance(
    instance_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Stream agent execution events via Server-Sent Events (SSE).

    Tails the Redis Streams event bus for events matching this instance,
    delivering step-by-step progress in real time.
    """
    import asyncio
    import json

    from starlette.responses import StreamingResponse

    from app.config import settings
    from app.core.redis import redis_pool

    await set_tenant_context(db, str(tenant.id))

    # Verify instance belongs to tenant
    instance = await db.get(AgentInstance, instance_id)
    if not instance or instance.tenant_id != tenant.id:
        raise HTTPException(404, "Instance not found")

    async def event_generator():
        """Generate SSE events from Redis Streams."""
        stream_key = f"{settings.EVENT_BUS_STREAM_PREFIX}:agent"
        last_id = "$"  # Start from now
        instance_str = str(instance_id)

        # Send initial status
        yield f"data: {json.dumps({'type': 'status', 'status': instance.status.value, 'instance_id': instance_str})}\n\n"

        # If already completed/failed, send final status and close
        if instance.status in (InstanceStatus.COMPLETED, InstanceStatus.FAILED, InstanceStatus.CANCELLED):
            yield f"data: {json.dumps({'type': 'done', 'status': instance.status.value, 'output': instance.output_data})}\n\n"
            return

        max_duration = settings.AGENT_MAX_DURATION_SECONDS + 60  # Extra buffer
        elapsed = 0.0

        while elapsed < max_duration:
            try:
                # Read from Redis Streams with blocking
                messages = await redis_pool.xread(
                    {stream_key: last_id},
                    count=10,
                    block=2000,  # 2 second blocking read
                )
            except Exception:
                # Redis unavailable - wait and retry
                await asyncio.sleep(2)
                elapsed += 2
                continue

            if messages:
                for stream_name, entries in messages:
                    for entry_id, fields in entries:
                        last_id = entry_id if isinstance(entry_id, str) else entry_id.decode()

                        # Parse event data
                        event_data = {}
                        for k, v in fields.items():
                            key = k if isinstance(k, str) else k.decode()
                            val = v if isinstance(v, str) else v.decode()
                            event_data[key] = val

                        # Filter for this instance's events
                        if event_data.get("instance_id") != instance_str:
                            continue

                        event_type = event_data.get("event_type", "unknown")

                        yield f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"

                        # Check for terminal events
                        if event_type in (
                            "AgentInstanceCompleted",
                            "AgentInstanceFailed",
                            "AgentInstanceStopped",
                        ):
                            yield f"data: {json.dumps({'type': 'done', 'event_type': event_type})}\n\n"
                            return
            else:
                elapsed += 2
                # Send keepalive
                yield ": keepalive\n\n"

                # Check DB for status change (in case we missed the event)
                await db.expire(instance)
                await db.refresh(instance)
                if instance.status in (InstanceStatus.COMPLETED, InstanceStatus.FAILED, InstanceStatus.CANCELLED):
                    yield f"data: {json.dumps({'type': 'done', 'status': instance.status.value, 'output': instance.output_data})}\n\n"
                    return

        yield f"data: {json.dumps({'type': 'timeout'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


# ── Conversations (Multi-Turn Interactive Sessions) ────────────────────


@router.post(
    "/definitions/{agent_id}/conversations",
    dependencies=[Depends(RequireScopes("agents:execute"))],
)
async def start_conversation(
    agent_id: uuid.UUID,
    body: ConversationStartRequest,
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Start a new interactive conversation with an agent.

    Creates an interactive AgentSession and executes the first turn,
    streaming SSE events in real-time. The session_id is returned in
    the first SSE event for use in subsequent reply calls.
    """
    from datetime import UTC, datetime as _dt

    from starlette.responses import StreamingResponse

    from app.agents.runtime import AgentRuntime
    from app.config import settings

    await set_tenant_context(db, str(tenant.id))

    from app.billing.entitlements import EntitlementDenied, entitlements
    try:
        await entitlements.require_feature(tenant.id, "agents:execute", db=db)
    except EntitlementDenied:
        raise HTTPException(403, "Feature not available on your current plan") from None

    agent = await _get_agent_or_404(db, agent_id, tenant.id)
    if agent.status != AgentStatus.ACTIVE:
        raise HTTPException(400, f"Agent '{agent.name}' is not active")

    await _enforce_concurrent_limit(db, agent, tenant.id)

    # Rate limit: max 10 session creations per minute per tenant
    from app.core.redis import redis_pool as _redis
    _rate_key = f"agent:conv:create:rate:{tenant.id}"
    try:
        _pipe = _redis.pipeline()
        _pipe.incr(_rate_key)
        _pipe.expire(_rate_key, 60)
        _rate_results = await _pipe.execute()
        if _rate_results[0] > 10:
            raise HTTPException(429, "Session creation rate limit exceeded (10/minute)")
    except HTTPException:
        raise
    except Exception:
        logger.error("conv_rate_limit_redis_unavailable", exc_info=True)
        if not getattr(settings, "AGENT_RATE_LIMIT_FAIL_OPEN", False):
            raise HTTPException(503, "Rate limiting service unavailable") from None

    # Resolve API key
    from app.core.encryption import decrypt
    from app.db.models.ai import TenantAIProviderKey
    from sqlalchemy import select as _select

    provider_key_result = await db.execute(
        _select(TenantAIProviderKey).where(
            TenantAIProviderKey.tenant_id == tenant.id,
            TenantAIProviderKey.is_active.is_(True),
        ).limit(1)
    )
    provider_key = provider_key_result.scalar_one_or_none()
    resolved_api_key = decrypt(provider_key.encrypted_api_key) if provider_key else ""
    if not resolved_api_key:
        raise HTTPException(503, "No AI provider key configured for this tenant")

    runtime = AgentRuntime(
        definition=agent,
        tenant_id=tenant.id,
        api_key=resolved_api_key,
        key_source="platform",
    )

    now = _dt.now(UTC)
    instance_id = uuid.uuid4()
    session_id = uuid.uuid4()

    idle_timeout = body.idle_timeout_seconds or settings.AGENT_SESSION_IDLE_TIMEOUT_SECONDS

    # Create interactive session
    from datetime import timedelta as _timedelta
    session = AgentSession(
        id=session_id,
        tenant_id=tenant.id,
        instance_id=instance_id,  # First instance that created this session
        definition_id=agent.id,
        status=SessionStatus.ACTIVE,
        is_interactive=True,
        messages=[],
        last_activity_at=now,
        idle_timeout_seconds=idle_timeout,
        expires_at=now + _timedelta(seconds=idle_timeout),
    )
    db.add(session)

    # Create first instance linked to session
    instance = AgentInstance(
        id=instance_id,
        tenant_id=tenant.id,
        definition_id=agent.id,
        session_id=session_id,
        status=InstanceStatus.RUNNING,
        input_data=body.input_data,
        started_at=now,
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    await db.refresh(session)

    await emit(ConversationStarted(
        tenant_id=str(tenant.id), session_id=str(session_id), agent_id=str(agent.id),
    ))

    messages = body.input_data.get("messages", [])
    if not messages and "prompt" in body.input_data:
        messages = [{"role": "user", "content": str(body.input_data["prompt"])}]
    if not messages:
        messages = [{"role": "user", "content": str(body.input_data)}]

    async def event_generator():
        import json as _json

        _completed_normally = False
        _final_data: dict = {}
        _assistant_messages: list[dict] = []

        # First event: session info so frontend can track the conversation
        yield (
            f"event: session_started\n"
            f"data: {_json.dumps({'session_id': str(session_id), 'instance_id': str(instance_id), 'definition_id': str(agent.id)})}\n\n"
        )

        try:
            async for event in runtime.run_stream(
                messages=messages,
                instance_id=instance_id,
                db=db,
            ):
                if await request.is_disconnected():
                    runtime.cancel()
                    return

                event_type = event.get("event", "message")
                event_data = event.get("data", {})

                if event_type == "run_completed":
                    _completed_normally = True
                    _final_data = event_data
                    if event_data.get("output"):
                        _assistant_messages.append({
                            "role": "assistant",
                            "content": str(event_data["output"]),
                        })

                yield f"event: {event_type}\ndata: {_json.dumps(event_data, default=str)}\n\n"
        except HTTPException as exc:
            import json as _json2
            logger.error("conversation_stream_error", error=exc.detail, exc_info=True)
            yield f"event: error\ndata: {_json2.dumps({'message': exc.detail})}\n\n"
        except Exception:
            import json as _json2
            logger.error("conversation_stream_error", exc_info=True)
            yield f"event: error\ndata: {_json2.dumps({'message': 'An internal error occurred. Please try again.'})}\n\n"
        finally:
            try:
                inst = await db.get(AgentInstance, instance_id)
                sess = await db.get(AgentSession, session_id)
                if inst and inst.status in (InstanceStatus.RUNNING, InstanceStatus.PENDING):
                    if _completed_normally:
                        inst.status = InstanceStatus.COMPLETED
                        inst.output_data = _final_data.get("output", {})
                        inst.tokens_used = _final_data.get("total_tokens", 0)
                        inst.cost_usd = _final_data.get("total_cost_usd", 0)
                        inst.steps_executed = _final_data.get("steps", 0)
                    elif runtime._cancelled:
                        inst.status = InstanceStatus.CANCELLED
                    else:
                        inst.status = InstanceStatus.FAILED
                        inst.error = "Stream terminated unexpectedly"
                    inst.completed_at = _dt.now(UTC)

                # Update session with conversation history and metrics
                if sess:
                    stored_messages = list(sess.messages or [])
                    stored_messages.extend(messages)
                    stored_messages.extend(_assistant_messages)
                    # Bound message history to prevent unbounded JSONB growth
                    max_messages = getattr(settings, "AGENT_SESSION_MAX_MESSAGES", 200)
                    if len(stored_messages) > max_messages:
                        stored_messages = stored_messages[-max_messages:]
                    sess.messages = stored_messages
                    sess.turn_count = 1
                    sess.total_tokens = _final_data.get("total_tokens", 0)
                    sess.total_cost_usd = float(_final_data.get("total_cost_usd", 0))
                    sess.last_activity_at = _dt.now(UTC)

                await db.commit()
            except Exception:
                logger.error(
                    "conversation_cleanup_failed",
                    instance_id=str(instance_id),
                    session_id=str(session_id),
                    exc_info=True,
                )
                # Fallback: attempt to at least mark instance as failed
                try:
                    await db.rollback()
                    inst = await db.get(AgentInstance, instance_id)
                    if inst and inst.status == InstanceStatus.RUNNING:
                        inst.status = InstanceStatus.FAILED
                        inst.error = "Cleanup failed"
                        inst.completed_at = _dt.now(UTC)
                        await db.commit()
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Instance-Id": str(instance_id),
            "X-Session-Id": str(session_id),
            "Access-Control-Expose-Headers": "X-Instance-Id, X-Session-Id",
        },
    )


@router.post(
    "/sessions/{session_id}/reply",
    dependencies=[Depends(RequireScopes("agents:execute"))],
)
async def conversation_reply(
    session_id: uuid.UUID,
    body: ConversationReplyRequest,
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Send a follow-up message in an existing interactive conversation.

    Validates the session is still active and not locked by another reply,
    then creates a new AgentInstance for this turn and streams SSE events.
    """
    from datetime import UTC, datetime as _dt

    from starlette.responses import StreamingResponse

    from app.agents.runtime import AgentRuntime
    from app.config import settings

    await set_tenant_context(db, str(tenant.id))

    # Load and validate session
    session = await db.get(AgentSession, session_id)
    if not session or session.tenant_id != tenant.id:
        raise HTTPException(404, "Session not found")
    if not session.is_interactive:
        raise HTTPException(400, "Session is not interactive — use run-stream for one-shot runs")
    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(400, f"Session is {session.status.value}, cannot accept replies")

    # Check session expiry
    now = _dt.now(UTC)
    if session.expires_at and session.expires_at < now:
        raise HTTPException(410, "Session has expired")
    if session.last_activity_at:
        from datetime import timedelta
        idle_deadline = session.last_activity_at + timedelta(seconds=session.idle_timeout_seconds)
        if now > idle_deadline:
            session.status = SessionStatus.EXPIRED
            await db.commit()
            raise HTTPException(410, "Session has expired due to inactivity")

    # Rate limit: max 20 replies per minute per session
    from app.core.redis import redis_pool as _redis_reply
    _reply_rate_key = f"agent:conv:reply:rate:{session_id}"
    try:
        _pipe = _redis_reply.pipeline()
        _pipe.incr(_reply_rate_key)
        _pipe.expire(_reply_rate_key, 60)
        _rate_results = await _pipe.execute()
        if _rate_results[0] > 20:
            raise HTTPException(429, "Reply rate limit exceeded (20/minute)")
    except HTTPException:
        raise
    except Exception:
        logger.error("reply_rate_limit_redis_unavailable", exc_info=True)
        if not getattr(settings, "AGENT_RATE_LIMIT_FAIL_OPEN", False):
            raise HTTPException(503, "Rate limiting service unavailable") from None

    # Check turn limit
    if session.turn_count >= settings.AGENT_SESSION_MAX_TURNS:
        raise HTTPException(
            429,
            f"Session has reached the maximum number of turns ({settings.AGENT_SESSION_MAX_TURNS})",
        )

    # Acquire Redis distributed lock to prevent concurrent replies
    from app.core.redis import redis_pool
    lock_key = f"agent:session:lock:{session_id}"
    lock = redis_pool.lock(lock_key, timeout=settings.AGENT_CONVERSATION_LOCK_TIMEOUT, blocking_timeout=0)
    if not await lock.acquire():
        raise HTTPException(409, "A response is still in progress for this session")

    # Pre-generator setup — if anything here raises, release lock immediately
    try:
        # Re-validate session after lock (TOCTOU protection)
        await db.refresh(session)
        now = _dt.now(UTC)
        if session.status != SessionStatus.ACTIVE:
            raise HTTPException(400, f"Session is {session.status.value}, cannot accept replies")
        if session.expires_at and session.expires_at < now:
            session.status = SessionStatus.EXPIRED
            await db.commit()
            raise HTTPException(410, "Session has expired")

        # Load agent definition
        agent = await db.get(AgentDefinition, session.definition_id)
        if not agent or agent.status != AgentStatus.ACTIVE:
            raise HTTPException(400, "Agent is no longer active")

        await _enforce_concurrent_limit(db, agent, tenant.id)

        # Resolve API key
        from app.core.encryption import decrypt
        from app.db.models.ai import TenantAIProviderKey
        from sqlalchemy import select as _select

        provider_key_result = await db.execute(
            _select(TenantAIProviderKey).where(
                TenantAIProviderKey.tenant_id == tenant.id,
                TenantAIProviderKey.is_active.is_(True),
            ).limit(1)
        )
        provider_key = provider_key_result.scalar_one_or_none()
        resolved_api_key = decrypt(provider_key.encrypted_api_key) if provider_key else ""
        if not resolved_api_key:
            raise HTTPException(503, "No AI provider key configured for this tenant")

        runtime = AgentRuntime(
            definition=agent,
            tenant_id=tenant.id,
            api_key=resolved_api_key,
            key_source="platform",
        )

        instance_id = uuid.uuid4()
        new_user_message = {"role": "user", "content": body.message}
        turn_number = session.turn_count + 1

        # Build full conversation from session history + new message
        conversation_messages = list(session.messages or [])
        conversation_messages.append(new_user_message)

        # Create new instance for this turn
        instance = AgentInstance(
            id=instance_id,
            tenant_id=tenant.id,
            definition_id=agent.id,
            session_id=session_id,
            status=InstanceStatus.RUNNING,
            input_data={"messages": [new_user_message]},
            started_at=now,
        )
        db.add(instance)
        await db.commit()
        await db.refresh(instance)
    except Exception:
        try:
            await lock.release()
        except Exception:
            logger.warning("session_lock_release_failed", session_id=str(session_id))
        raise

    # Lock ownership transfers to the generator — no outer release needed
    async def event_generator():
        import json as _json

        _completed_normally = False
        _final_data: dict = {}
        _assistant_messages: list[dict] = []

        yield (
            f"event: turn_started\n"
            f"data: {_json.dumps({'instance_id': str(instance_id), 'session_id': str(session_id), 'turn_number': turn_number})}\n\n"
        )

        try:
            async for event in runtime.run_stream(
                messages=conversation_messages,
                instance_id=instance_id,
                db=db,
            ):
                if await request.is_disconnected():
                    runtime.cancel()
                    return

                event_type = event.get("event", "message")
                event_data = event.get("data", {})

                if event_type == "run_completed":
                    _completed_normally = True
                    _final_data = event_data
                    if event_data.get("output"):
                        _assistant_messages.append({
                            "role": "assistant",
                            "content": str(event_data["output"]),
                        })

                yield f"event: {event_type}\ndata: {_json.dumps(event_data, default=str)}\n\n"
        except HTTPException as exc:
            import json as _json2
            logger.error("conversation_reply_error", error=exc.detail, exc_info=True)
            yield f"event: error\ndata: {_json2.dumps({'message': exc.detail})}\n\n"
        except Exception:
            import json as _json2
            logger.error("conversation_reply_error", exc_info=True)
            yield f"event: error\ndata: {_json2.dumps({'message': 'An internal error occurred. Please try again.'})}\n\n"
        finally:
            try:
                inst = await db.get(AgentInstance, instance_id)
                sess = await db.get(AgentSession, session_id)

                if inst and inst.status in (InstanceStatus.RUNNING, InstanceStatus.PENDING):
                    if _completed_normally:
                        inst.status = InstanceStatus.COMPLETED
                        inst.output_data = _final_data.get("output", {})
                        inst.tokens_used = _final_data.get("total_tokens", 0)
                        inst.cost_usd = _final_data.get("total_cost_usd", 0)
                        inst.steps_executed = _final_data.get("steps", 0)
                    elif runtime._cancelled:
                        inst.status = InstanceStatus.CANCELLED
                    else:
                        inst.status = InstanceStatus.FAILED
                        inst.error = "Stream terminated unexpectedly"
                    inst.completed_at = _dt.now(UTC)

                # Update session with new messages and metrics
                if sess:
                    stored_messages = list(sess.messages or [])
                    stored_messages.append(new_user_message)
                    stored_messages.extend(_assistant_messages)
                    # Bound message history to prevent unbounded JSONB growth
                    max_messages = getattr(settings, "AGENT_SESSION_MAX_MESSAGES", 200)
                    if len(stored_messages) > max_messages:
                        stored_messages = stored_messages[-max_messages:]
                    sess.messages = stored_messages
                    sess.turn_count = turn_number
                    sess.total_tokens = (sess.total_tokens or 0) + _final_data.get("total_tokens", 0)
                    sess.total_cost_usd = float(sess.total_cost_usd or 0) + float(_final_data.get("total_cost_usd", 0))
                    sess.last_activity_at = _dt.now(UTC)

                    # Sliding TTL: extend expiry on each turn
                    if settings.AGENT_SESSION_SLIDING_TTL:
                        from datetime import timedelta
                        sess.expires_at = _dt.now(UTC) + timedelta(seconds=sess.idle_timeout_seconds)

                await db.commit()

                if _completed_normally:
                    await emit(ConversationTurnCompleted(
                        tenant_id=str(tenant.id),
                        session_id=str(session_id),
                        instance_id=str(instance_id),
                        turn_number=turn_number,
                        tokens_used=_final_data.get("total_tokens", 0),
                        cost_usd=float(_final_data.get("total_cost_usd", 0)),
                    ))
            except Exception:
                logger.error(
                    "conversation_reply_cleanup_failed",
                    instance_id=str(instance_id),
                    session_id=str(session_id),
                    exc_info=True,
                )
                # Fallback: attempt to at least mark instance as failed
                try:
                    await db.rollback()
                    inst = await db.get(AgentInstance, instance_id)
                    if inst and inst.status == InstanceStatus.RUNNING:
                        inst.status = InstanceStatus.FAILED
                        inst.error = "Cleanup failed"
                        inst.completed_at = _dt.now(UTC)
                        await db.commit()
                except Exception:
                    pass
            finally:
                # Always release the lock
                try:
                    await lock.release()
                except Exception:
                    logger.warning("session_lock_release_failed", session_id=str(session_id))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Instance-Id": str(instance_id),
            "X-Session-Id": str(session_id),
            "Access-Control-Expose-Headers": "X-Instance-Id, X-Session-Id",
        },
    )


@router.get(
    "/sessions/{session_id}",
    response_model=ConversationSessionResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def get_session(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get a session by ID with full message history."""
    await set_tenant_context(db, str(tenant.id))
    session = await db.get(AgentSession, session_id)
    if not session or session.tenant_id != tenant.id:
        raise HTTPException(404, "Session not found")
    return ConversationSessionResponse.model_validate(session)


@router.post(
    "/sessions/{session_id}/close",
    response_model=ConversationSessionResponse,
    dependencies=[Depends(RequireScopes("agents:execute"))],
)
async def close_session(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Explicitly close an interactive conversation session."""
    await set_tenant_context(db, str(tenant.id))
    session = await db.get(AgentSession, session_id)
    if not session or session.tenant_id != tenant.id:
        raise HTTPException(404, "Session not found")
    if session.status == SessionStatus.COMPLETED:
        return ConversationSessionResponse.model_validate(session)
    session.status = SessionStatus.COMPLETED
    await db.commit()
    await db.refresh(session)

    await emit(ConversationEnded(
        tenant_id=str(tenant.id),
        session_id=str(session_id),
        total_turns=session.turn_count,
        total_tokens=session.total_tokens or 0,
        total_cost_usd=float(session.total_cost_usd or 0),
    ))

    return ConversationSessionResponse.model_validate(session)


@router.get(
    "/definitions/{agent_id}/conversations",
    response_model=PaginatedResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_conversations(
    agent_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List interactive conversation sessions for an agent definition."""
    await set_tenant_context(db, str(tenant.id))
    await _get_agent_or_404(db, agent_id, tenant.id)

    conditions = [
        AgentSession.definition_id == agent_id,
        AgentSession.tenant_id == tenant.id,
        AgentSession.is_interactive.is_(True),
    ]
    if status:
        conditions.append(AgentSession.status == status)

    count_stmt = select(func.count()).select_from(AgentSession).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(AgentSession)
        .where(*conditions)
        .order_by(AgentSession.last_activity_at.desc().nullslast(), AgentSession.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=[ConversationSessionResponse.model_validate(s) for s in items],
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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Write an agent memory entry (rate-limited per instance)."""
    from app.agents.memory import AgentMemoryManager
    from app.core.redis import redis_pool

    await set_tenant_context(db, str(tenant.id))
    await _verify_instance_ownership(db, instance_id, tenant.id)

    # Per-instance write rate limit (60 writes/minute)
    # Use pipeline to make INCR+EXPIRE atomic (prevents permanent keys).
    rate_key = f"agent:memory:rate:{instance_id}"
    try:
        pipe = redis_pool.pipeline()
        pipe.incr(rate_key)
        pipe.expire(rate_key, 60)  # Always refresh TTL
        results = await pipe.execute()
        current = results[0]
        if current > 60:
            raise HTTPException(429, "Memory write rate limit exceeded (60/minute)")
    except HTTPException:
        raise
    except Exception:
        logger.error("memory_rate_limit_redis_unavailable", instance_id=str(instance_id), exc_info=True)
        raise HTTPException(503, "Rate limiter unavailable. Please retry later.") from None

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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Clear agent memory."""
    from app.agents.memory import AgentMemoryManager
    await set_tenant_context(db, str(tenant.id))
    await _verify_instance_ownership(db, instance_id, tenant.id)
    memory = AgentMemoryManager(db)
    await memory.clear_long_term(instance_id, tenant.id, namespace)
    await db.commit()


# ── Definition-Scoped Shared Memory ────────────────────────────────────


@router.get(
    "/definitions/{agent_id}/memory",
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def read_definition_memory(
    agent_id: uuid.UUID,
    namespace: str = "shared",
    key: str | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Read definition-scoped shared memory (accessible by all instances)."""
    from app.agents.memory import AgentMemoryManager
    await set_tenant_context(db, str(tenant.id))
    await _get_agent_or_404(db, agent_id, tenant.id)
    memory = AgentMemoryManager(db)

    if key:
        value = await memory.get_definition_memory(agent_id, tenant.id, key, namespace)
        if value is None:
            raise HTTPException(404, "Memory entry not found")
        return {"namespace": namespace, "key": key, "value": value}
    else:
        entries = await memory.list_definition_memory(agent_id, tenant.id, namespace)
        return [
            {"namespace": e.namespace, "key": e.key, "value": e.value}
            for e in entries
        ]


@router.put(
    "/definitions/{agent_id}/memory",
    dependencies=[Depends(RequireScopes("agents:write"))],
)
async def write_definition_memory(
    agent_id: uuid.UUID,
    body: MemoryWriteRequest,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Write to definition-scoped shared memory (accessible by all instances)."""
    from app.agents.memory import AgentMemoryManager
    from app.core.redis import redis_pool
    await set_tenant_context(db, str(tenant.id))
    await _get_agent_or_404(db, agent_id, tenant.id)

    # Per-definition write rate limit (60 writes/minute) — fail closed
    rate_key = f"agent:def_memory:rate:{agent_id}"
    try:
        pipe = redis_pool.pipeline()
        pipe.incr(rate_key)
        pipe.expire(rate_key, 60)
        results = await pipe.execute()
        current = results[0]
        if current > 60:
            raise HTTPException(429, "Definition memory write rate limit exceeded (60/minute)")
    except HTTPException:
        raise
    except Exception:
        logger.error("def_memory_rate_limit_redis_unavailable", agent_id=str(agent_id), exc_info=True)
        raise HTTPException(503, "Rate limiter unavailable. Please retry later.") from None

    memory = AgentMemoryManager(db)

    entry = await memory.set_definition_memory(
        agent_id, tenant.id, body.key, body.value, namespace=body.namespace,
    )
    await db.commit()
    return {"namespace": entry.namespace, "key": entry.key, "value": entry.value}


@router.delete(
    "/definitions/{agent_id}/memory",
    status_code=204,
    dependencies=[Depends(RequireScopes("agents:admin"))],
)
async def clear_definition_memory(
    agent_id: uuid.UUID,
    namespace: str | None = None,
    key: str | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Clear definition-scoped shared memory."""
    from app.agents.memory import AgentMemoryManager
    await set_tenant_context(db, str(tenant.id))
    await _get_agent_or_404(db, agent_id, tenant.id)
    memory = AgentMemoryManager(db)

    if key:
        await memory.delete_definition_memory(agent_id, tenant.id, key, namespace or "shared")
    else:
        # Clear all entries in namespace (or all namespaces)
        from sqlalchemy import delete as sql_delete
        from app.agents.models import AgentDefinitionMemoryEntry
        conditions = [
            AgentDefinitionMemoryEntry.definition_id == agent_id,
            AgentDefinitionMemoryEntry.tenant_id == tenant.id,
        ]
        if namespace:
            conditions.append(AgentDefinitionMemoryEntry.namespace == namespace)
        await db.execute(sql_delete(AgentDefinitionMemoryEntry).where(*conditions))
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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
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
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Workflow with slug '{body.slug}' already exists") from exc
    await db.refresh(workflow)
    await db.commit()
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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Execute a workflow (async via Celery)."""
    await set_tenant_context(db, str(tenant.id))

    from app.billing.entitlements import entitlements, EntitlementDenied
    try:
        await entitlements.require_feature(tenant.id, "agents:workflow", db=db)
    except EntitlementDenied:
        raise HTTPException(403, "Feature not available on your current plan") from None

    workflow = await db.get(WorkflowDefinition, workflow_id)
    if not workflow or workflow.tenant_id != tenant.id or workflow.deleted_at:
        raise HTTPException(404, "Workflow not found")
    if workflow.status != WorkflowStatus.ACTIVE:
        raise HTTPException(400, "Workflow is not active")

    # TODO: Add idempotency_key support to WorkflowRunCreate schema and
    # implement deduplication logic (similar to create_agent_instance) to
    # prevent duplicate workflow runs on client retries.

    # Create run record
    run = WorkflowRun(
        tenant_id=tenant.id,
        workflow_id=workflow_id,
        input_data=body.input_data,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    await db.commit()

    # Dispatch to Celery
    from app.agents.tasks import execute_workflow_run
    execute_workflow_run.delay(
        workflow_id=str(workflow_id),
        tenant_id=str(tenant.id),
        input_data=body.input_data,
        api_key_id=str(api_key.id) if api_key else None,  # Worker resolves key by ID
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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Register a custom tool for agents."""
    await set_tenant_context(db, str(tenant.id))

    # Encrypt all sensitive auth_config fields before storage
    encrypted_auth_config = dict(body.auth_config) if body.auth_config else {}
    if encrypted_auth_config:
        from app.core.encryption import encrypt
        for field_name in _AUTH_SENSITIVE_KEYS:
            if encrypted_auth_config.get(field_name):
                encrypted_auth_config[field_name] = encrypt(encrypted_auth_config[field_name])

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
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Tool '{body.tool_name}' already exists") from exc
    await db.refresh(tool)
    await db.commit()
    return tool


@router.get(
    "/tools",
    response_model=PaginatedResponse,
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def list_tools(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all tools available to agents (built-in + custom)."""
    await set_tenant_context(db, str(tenant.id))

    conditions = [
        TenantTool.tenant_id == tenant.id,
        TenantTool.is_active.is_(True),
        TenantTool.deleted_at.is_(None),
    ]
    count_stmt = select(func.count()).select_from(TenantTool).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(TenantTool)
        .where(*conditions)
        .order_by(TenantTool.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=[TenantToolResponse.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.delete(
    "/tools/{tool_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("agents:admin"))],
)
async def remove_tenant_tool(
    tool_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
    db: AsyncSession = Depends(get_db),
):
    """Remove a custom tool."""
    from datetime import UTC, datetime
    await set_tenant_context(db, str(tenant.id))
    tool = await db.get(TenantTool, tool_id)
    if not tool or tool.tenant_id != tenant.id or tool.deleted_at:
        raise HTTPException(404, "Tool not found")
    tool.deleted_at = datetime.now(UTC)
    tool.is_active = False
    await db.commit()


# ── Agent Approvals (HITL) ─────────────────────────────────────────────


@router.get(
    "/approvals",
    dependencies=[Depends(RequireScopes("agents:admin"))],
)
async def list_pending_approvals(
    tenant: Tenant = Depends(get_current_tenant),
):
    """List pending agent approval requests for the current tenant."""
    from app.agents.governance import GovernanceEngine
    approvals = await GovernanceEngine.list_pending_approvals(tenant.id)
    return {"approvals": approvals, "count": len(approvals)}


@router.post(
    "/approvals/{approval_id}/resolve",
    dependencies=[Depends(RequireScopes("agents:admin"))],
)
async def resolve_approval(
    approval_id: str,
    body: dict,
    tenant: Tenant = Depends(get_current_tenant),
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
):
    """Resolve a pending agent approval request.

    Body: {"decision": "approved" | "denied"}
    """
    from app.agents.governance import GovernanceEngine

    import re as _re
    if not _re.match(r'^[a-f0-9]{32}$', approval_id):
        raise HTTPException(400, "Invalid approval ID format")

    decision = body.get("decision")
    if decision not in ("approved", "denied"):
        raise HTTPException(400, "decision must be 'approved' or 'denied'")

    # Verify tenant ownership BEFORE resolving to prevent TOCTOU where
    # state is mutated before the ownership check rejects the caller.
    import json as _json
    from app.core.redis import redis_pool as _redis

    _approval_key = f"agent:gov:approval:{approval_id}"
    _raw = await _redis.get(_approval_key)
    if not _raw:
        raise HTTPException(404, "Approval request not found or expired")
    _approval_data = _json.loads(_raw)
    if _approval_data.get("tenant_id") != str(tenant.id):
        raise HTTPException(404, "Approval request not found")

    result = await GovernanceEngine.resolve_approval(
        approval_id=approval_id,
        decision=decision,
        resolved_by=str(api_key.id) if api_key else "jwt-user",
    )

    if result is None:
        raise HTTPException(404, "Approval request not found or expired")

    return result


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
    api_key: ApiKey | None = Depends(get_current_api_key_optional),
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
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Policy with name '{body.name}' already exists") from exc
    await db.refresh(policy)
    await db.commit()
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


# ── Agent Analytics ─────────────────────────────────────────────────────


@router.get(
    "/analytics",
    dependencies=[Depends(RequireScopes("agents:read"))],
)
async def get_agent_analytics(
    days: int = Query(30, ge=1, le=365),
    agent_id: uuid.UUID | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate agent analytics (spending, tokens, runs by time period).

    Optionally filter by a specific agent definition.
    """
    from datetime import UTC, datetime, timedelta

    await set_tenant_context(db, str(tenant.id))

    cutoff = datetime.now(UTC) - timedelta(days=days)

    conditions = [
        AgentInstance.tenant_id == tenant.id,
        AgentInstance.created_at >= cutoff,
    ]
    if agent_id:
        conditions.append(AgentInstance.definition_id == agent_id)

    # Aggregate metrics
    result = await db.execute(
        select(
            func.count(AgentInstance.id).label("total_runs"),
            func.sum(AgentInstance.tokens_used).label("total_tokens"),
            func.sum(AgentInstance.cost_usd).label("total_cost_usd"),
            func.avg(AgentInstance.cost_usd).label("avg_cost_per_run"),
            func.avg(AgentInstance.steps_executed).label("avg_steps_per_run"),
        ).where(*conditions)
    )
    row = result.one()

    # Breakdown by status
    status_result = await db.execute(
        select(
            AgentInstance.status,
            func.count(AgentInstance.id).label("count"),
        )
        .where(*conditions)
        .group_by(AgentInstance.status)
    )
    status_breakdown = {
        r[0].value: r[1] for r in status_result.all()
    }

    # Top agents by cost
    top_agents_result = await db.execute(
        select(
            AgentInstance.definition_id,
            AgentDefinition.name,
            func.count(AgentInstance.id).label("runs"),
            func.sum(AgentInstance.cost_usd).label("total_cost"),
            func.sum(AgentInstance.tokens_used).label("total_tokens"),
        )
        .join(AgentDefinition, AgentInstance.definition_id == AgentDefinition.id)
        .where(*conditions)
        .group_by(AgentInstance.definition_id, AgentDefinition.name)
        .order_by(func.sum(AgentInstance.cost_usd).desc())
        .limit(10)
    )
    top_agents = [
        {
            "agent_id": str(r[0]),
            "name": r[1],
            "runs": r[2],
            "total_cost_usd": float(r[3] or 0),
            "total_tokens": r[4] or 0,
        }
        for r in top_agents_result.all()
    ]

    return {
        "period_days": days,
        "total_runs": row[0] or 0,
        "total_tokens": row[1] or 0,
        "total_cost_usd": float(row[2] or 0),
        "avg_cost_per_run": float(row[3] or 0),
        "avg_steps_per_run": float(row[4] or 0),
        "status_breakdown": status_breakdown,
        "top_agents": top_agents,
    }


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
