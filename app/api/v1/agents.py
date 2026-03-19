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

# Sensitive field names in auth_config that must be encrypted/masked
_AUTH_SENSITIVE_KEYS = {"token", "key", "secret", "password", "client_secret", "api_key"}

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
        parallel_tool_execution=body.parallel_tool_execution,
        memory_config=body.memory_config,
        governance_policy=body.governance_policy,
        metadata_=body.metadata,
    )
    db.add(agent)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Agent with slug '{body.slug}' already exists") from exc
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

    # Optimistic concurrency control
    if body.expected_version is not None and agent.version != body.expected_version:
        raise HTTPException(409, "Agent was modified concurrently. Refresh and retry.")

    # Allowlist of mutable fields to prevent mass-assignment of sensitive columns
    _MUTABLE_FIELDS = {
        "name", "slug", "description", "status", "system_prompt", "model",
        "temperature", "max_tokens", "allowed_tools", "tool_versions",
        "max_steps_per_run", "max_duration_seconds", "max_tokens_per_run",
        "sandbox_enabled", "parallel_tool_execution", "memory_config",
        "output_schema", "governance_policy", "metadata",
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
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Race: another request with the same key was inserted concurrently
        if existing_stmt is not None:
            existing_result = await db.execute(existing_stmt)
            existing_instance = existing_result.scalar_one_or_none()
            if existing_instance:
                return existing_instance
        raise HTTPException(409, "Duplicate idempotency key") from exc
    await db.refresh(instance)

    # Dispatch to Celery for async execution.
    # Use instance.id as the Celery task_id so stop_agent_instance can revoke it.
    from app.agents.tasks import execute_agent_run
    execute_agent_run.apply_async(
        kwargs={
            "definition_id": str(agent.id),
            "tenant_id": str(tenant.id),
            "input_data": body.input_data,
            "api_key_id": str(api_key.id),  # Worker resolves key by ID
            "key_source": "platform",
            "session_id": str(body.session_id) if body.session_id else None,
        },
        task_id=str(instance.id),
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
    api_key: ApiKey = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Run an agent definition with streaming SSE output.

    Streams step-by-step ReAct loop events (thinking, tool_call, tool_result,
    content_delta, step_completed, run_completed) in real-time.
    """
    from starlette.responses import StreamingResponse

    from app.agents.runtime import AgentRuntime

    await set_tenant_context(db, str(tenant.id))
    agent = await _get_agent_or_404(db, agent_id, tenant.id)

    if agent.status != AgentStatus.ACTIVE:
        raise HTTPException(400, f"Agent '{agent.name}' is not active")

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

    runtime = AgentRuntime(
        definition=agent,
        tenant_id=tenant.id,
        api_key=resolved_api_key,
        key_source="platform",
    )

    instance_id = uuid.uuid4()
    messages = body.input_data.get("messages", [{"role": "user", "content": str(body.input_data)}])

    async def event_generator():
        import json as _json

        try:
            async for event in runtime.run_stream(
                messages=messages,
                instance_id=instance_id,
                db=db,
            ):
                # Check client disconnect
                if await request.is_disconnected():
                    runtime.cancel()
                    return

                event_type = event.get("event", "message")
                event_data = event.get("data", {})
                yield f"event: {event_type}\ndata: {_json.dumps(event_data, default=str)}\n\n"
        except Exception as exc:
            import json as _json2
            yield f"event: error\ndata: {_json2.dumps({'message': str(exc)[:500]})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
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
        pass  # If Redis is down, allow the write

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
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Workflow with slug '{body.slug}' already exists") from exc
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
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Tool '{body.tool_name}' already exists") from exc
    await db.refresh(tool)
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
    api_key: ApiKey = Depends(get_current_api_key),
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
    api_key: ApiKey = Depends(get_current_api_key),
):
    """Resolve a pending agent approval request.

    Body: {"decision": "approved" | "denied"}
    """
    from app.agents.governance import GovernanceEngine

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
        resolved_by=str(api_key.id),
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
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, f"Policy with name '{body.name}' already exists") from exc
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
