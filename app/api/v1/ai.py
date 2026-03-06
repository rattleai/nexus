"""AI gateway API endpoints.

Provides unified multi-provider AI completions (sync, streaming, async),
BYOK key management, prepaid token wallet, prompt templates, and usage stats.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cost import calculate_billed_tokens, estimate_max_tokens
from app.ai.dependencies import AIQuotaEnforcer, RequireWalletBalance, require_ai_enabled
from app.ai.events import AIProviderKeyCreated, AIProviderKeyDeleted, WalletBalanceLow, WalletTopupCompleted
from app.ai.gateway import AIGatewayError, AIProviderUnavailableError, ai_gateway
from app.ai.guardrails import validate_input
from app.ai.key_resolver import NoAPIKeyError, resolve_api_key
from app.ai.metrics import AI_WALLET_BALANCE
from app.ai.providers import MODEL_CATALOG, get_model_info
from app.ai.schemas import (
    AICompletionRequest,
    AICompletionResponse,
    AIUsageResponse,
    ModelInfoResponse,
    ModelUsageSummary,
    PromptTemplateCreate,
    PromptTemplateResponse,
    PromptTemplateUpdate,
    ProviderKeyCreate,
    ProviderKeyResponse,
    WalletBalanceResponse,
    WalletTopupRequest,
    WalletTransactionResponse,
)
from app.ai.streaming import sse_stream_response
from app.ai.wallet import InsufficientBalanceError, wallet_service
from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.schemas import CursorPaginatedResponse, JobResponse
from app.config import settings
from app.core.events import emit
from app.core.quotas import increment_usage, QuotaMetric
from app.db.models.ai import AIProvider, AIUsageLog, PromptTemplate, TenantAIProviderKey
from app.db.models.core import Tenant
from app.db.models.operations import Job, JobStatus

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/ai", dependencies=[Depends(require_ai_enabled)])


# ── Completions ───────────────────────────────────────────


@router.post(
    "/completions",
    response_model=AICompletionResponse,
    dependencies=[
        Depends(RequireScopes("ai:write")),
        Depends(RequireWalletBalance()),
        Depends(AIQuotaEnforcer()),
    ],
    responses={
        402: {"description": "Insufficient wallet balance"},
        422: {"description": "Guardrail violation"},
        429: {"description": "Quota exceeded"},
        502: {"description": "AI provider unavailable"},
    },
)
async def create_completion(
    request: Request,
    body: AICompletionRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create an AI completion (sync or streaming).

    Set `stream: true` to receive Server-Sent Events (SSE).
    """
    model_info = get_model_info(body.model)
    if not model_info:
        raise HTTPException(status_code=400, detail=f"Unknown model: {body.model}")

    # Build messages list
    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    # Resolve prompt template if specified
    if body.template_id:
        result = await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.id == body.template_id,
                PromptTemplate.tenant_id == tenant.id,
                PromptTemplate.deleted_at.is_(None),
            )
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(status_code=404, detail="Prompt template not found")
        # Prepend system prompt
        messages.insert(0, {"role": "system", "content": template.system_prompt})

    # Input guardrails
    violations = validate_input(messages, tenant_settings=tenant.settings)
    if violations:
        raise HTTPException(
            status_code=422,
            detail=f"Input guardrail violation: {violations[0]}",
        )

    # Resolve API key
    try:
        api_key, key_source = await resolve_api_key(tenant.id, model_info.provider, db)
    except NoAPIKeyError:
        raise HTTPException(
            status_code=400,
            detail=f"No API key available for provider '{model_info.provider.value}'. "
            f"Configure a BYOK key or contact the platform administrator.",
        )

    request_id = uuid.uuid4().hex

    # Streaming path
    if body.stream:
        if not model_info.supports_streaming:
            raise HTTPException(status_code=400, detail=f"Model '{body.model}' does not support streaming")

        start_time = time.monotonic()
        litellm_stream = await ai_gateway.streaming_completion(
            tenant_id=tenant.id,
            model=body.model,
            messages=messages,
            api_key=api_key,
            key_source=key_source,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            top_p=body.top_p,
            request_id=request_id,
        )
        return await sse_stream_response(
            litellm_stream,
            model=body.model,
            provider=model_info.provider.value,
            key_source=key_source,
            request_id=request_id,
            start_time=start_time,
        )

    # Non-streaming path
    try:
        result = await ai_gateway.completion(
            tenant_id=tenant.id,
            model=body.model,
            messages=messages,
            api_key=api_key,
            key_source=key_source,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            top_p=body.top_p,
            fallback_models=body.fallback_models,
            request_id=request_id,
            tenant_settings=tenant.settings,
            db=db,
        )
    except AIProviderUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except AIGatewayError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Deduct from wallet
    try:
        new_balance = await wallet_service.deduct_tokens(
            tenant.id,
            result.billed_tokens,
            description=f"AI completion: {body.model}",
            reference_id=request_id,
            db=db,
        )
    except InsufficientBalanceError as exc:
        raise HTTPException(
            status_code=402,
            detail=str(exc),
            headers={"X-Wallet-Balance": str(exc.available)},
        )

    # Update Prometheus wallet gauge
    AI_WALLET_BALANCE.labels(tenant_id=str(tenant.id)).set(new_balance)

    # Check low balance warning
    if new_balance < settings.AI_WALLET_LOW_BALANCE_THRESHOLD:
        await emit(WalletBalanceLow(
            tenant_id=str(tenant.id),
            balance_tokens=new_balance,
            threshold=settings.AI_WALLET_LOW_BALANCE_THRESHOLD,
        ))

    # Record usage in quotas
    await increment_usage(tenant.id, QuotaMetric.AI_REQUESTS_DAY)
    await increment_usage(tenant.id, QuotaMetric.AI_TOKENS_MONTH, result.total_tokens)

    # Log usage to DB
    usage_log = AIUsageLog(
        tenant_id=tenant.id,
        provider=result.provider,
        model=body.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        cost_usd=result.cost_usd,
        billed_tokens=result.billed_tokens,
        latency_ms=result.latency_ms,
        status="success",
        key_source=result.key_source,
        request_id=request_id,
    )
    db.add(usage_log)
    await db.commit()

    return AICompletionResponse(
        id=result.id,
        model=result.model,
        content=result.content,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        billed_tokens=result.billed_tokens,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        key_source=result.key_source,
        finish_reason=result.finish_reason,
    )


@router.post(
    "/completions/async",
    response_model=JobResponse,
    dependencies=[
        Depends(RequireScopes("ai:write")),
        Depends(RequireWalletBalance()),
        Depends(AIQuotaEnforcer()),
    ],
)
async def create_async_completion(
    body: AICompletionRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Submit an AI completion for asynchronous processing via Celery.

    Returns a Job that can be polled for results.
    """
    model_info = get_model_info(body.model)
    if not model_info:
        raise HTTPException(status_code=400, detail=f"Unknown model: {body.model}")

    # Create job
    job = Job(
        tenant_id=tenant.id,
        type="ai_completion",
        status=JobStatus.PENDING,
        payload={
            "model": body.model,
            "messages": [m.model_dump() for m in body.messages],
            "max_tokens": body.max_tokens,
            "temperature": body.temperature,
            "top_p": body.top_p,
            "fallback_models": body.fallback_models,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Dispatch Celery task
    from app.ai.tasks import process_ai_completion

    process_ai_completion.delay(str(tenant.id), job.payload, str(job.id))

    logger.info("ai_async_completion_queued", job_id=str(job.id), model=body.model)

    return JobResponse.model_validate(job)


# ── Models ────────────────────────────────────────────────


@router.get(
    "/models",
    response_model=list[ModelInfoResponse],
    dependencies=[Depends(RequireScopes("ai:read"))],
)
async def list_models(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all available AI models with availability status."""
    from app.ai.key_resolver import check_key_availability

    models = []
    for model_id, info in MODEL_CATALOG.items():
        if info.deprecated:
            continue

        available, _source = await check_key_availability(tenant.id, info.provider, db)

        models.append(ModelInfoResponse(
            model_id=model_id,
            provider=info.provider.value,
            display_name=info.display_name,
            max_input_tokens=info.max_input_tokens,
            max_output_tokens=info.max_output_tokens,
            supports_streaming=info.supports_streaming,
            supports_function_calling=info.supports_function_calling,
            supports_vision=info.supports_vision,
            available=available,
        ))

    return models


# ── Provider Keys (BYOK) ─────────────────────────────────


@router.post(
    "/provider-keys",
    response_model=ProviderKeyResponse,
    dependencies=[Depends(RequireScopes("ai:admin"))],
    status_code=201,
)
async def create_provider_key(
    body: ProviderKeyCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Store an encrypted BYOK API key for an AI provider."""
    provider = AIProvider(body.provider)

    # Check for existing key with same name
    existing = await db.execute(
        select(TenantAIProviderKey).where(
            TenantAIProviderKey.tenant_id == tenant.id,
            TenantAIProviderKey.provider == provider,
            TenantAIProviderKey.display_name == body.display_name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"A key named '{body.display_name}' already exists for provider '{body.provider}'",
        )

    key_record = TenantAIProviderKey(
        tenant_id=tenant.id,
        provider=provider,
        display_name=body.display_name,
    )
    key_record.set_api_key(body.api_key)
    db.add(key_record)
    await db.commit()
    await db.refresh(key_record)

    await emit(AIProviderKeyCreated(
        tenant_id=str(tenant.id),
        provider=body.provider,
        key_id=str(key_record.id),
    ))

    logger.info("ai_provider_key_created", tenant_id=str(tenant.id), provider=body.provider)
    return ProviderKeyResponse.model_validate(key_record)


@router.get(
    "/provider-keys",
    response_model=list[ProviderKeyResponse],
    dependencies=[Depends(RequireScopes("ai:read"))],
)
async def list_provider_keys(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all BYOK provider keys for the tenant (keys are never returned)."""
    result = await db.execute(
        select(TenantAIProviderKey)
        .where(TenantAIProviderKey.tenant_id == tenant.id)
        .order_by(TenantAIProviderKey.created_at.desc())
    )
    return [ProviderKeyResponse.model_validate(k) for k in result.scalars().all()]


@router.delete(
    "/provider-keys/{key_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("ai:admin"))],
)
async def delete_provider_key(
    key_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Delete a BYOK provider key."""
    result = await db.execute(
        select(TenantAIProviderKey).where(
            TenantAIProviderKey.id == key_id,
            TenantAIProviderKey.tenant_id == tenant.id,
        )
    )
    key_record = result.scalar_one_or_none()
    if not key_record:
        raise HTTPException(status_code=404, detail="Provider key not found")

    provider = key_record.provider
    await db.delete(key_record)
    await db.commit()

    await emit(AIProviderKeyDeleted(
        tenant_id=str(tenant.id),
        provider=provider.value if hasattr(provider, "value") else str(provider),
        key_id=str(key_id),
    ))


# ── Wallet ────────────────────────────────────────────────


@router.get(
    "/wallet/balance",
    response_model=WalletBalanceResponse,
    dependencies=[Depends(RequireScopes("ai:read"))],
)
async def get_wallet_balance(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get the current token wallet balance."""
    wallet = await wallet_service._get_or_create_wallet(tenant.id, db)
    balance = await wallet_service.get_balance(tenant.id)
    if balance == 0 and wallet.balance_tokens > 0:
        await wallet_service.initialize_balance(tenant.id, db)
        balance = await wallet_service.get_balance(tenant.id)

    return WalletBalanceResponse(
        balance_tokens=balance,
        lifetime_purchased=wallet.lifetime_purchased,
        lifetime_consumed=wallet.lifetime_consumed,
    )


@router.post(
    "/wallet/topup",
    response_model=WalletBalanceResponse,
    dependencies=[Depends(RequireScopes("ai:admin"))],
)
async def topup_wallet(
    body: WalletTopupRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Top up the token wallet (after payment verification)."""
    new_balance = await wallet_service.topup(
        tenant.id,
        body.amount_tokens,
        reference_id=body.reference_id,
        description=f"Wallet topup: {body.amount_tokens} tokens",
        db=db,
    )

    await emit(WalletTopupCompleted(
        tenant_id=str(tenant.id),
        amount_tokens=body.amount_tokens,
        new_balance=new_balance,
        reference_id=body.reference_id or "",
    ))

    AI_WALLET_BALANCE.labels(tenant_id=str(tenant.id)).set(new_balance)

    wallet = await wallet_service._get_or_create_wallet(tenant.id, db)
    return WalletBalanceResponse(
        balance_tokens=new_balance,
        lifetime_purchased=wallet.lifetime_purchased,
        lifetime_consumed=wallet.lifetime_consumed,
    )


@router.get(
    "/wallet/transactions",
    response_model=CursorPaginatedResponse[WalletTransactionResponse],
    dependencies=[Depends(RequireScopes("ai:read"))],
)
async def list_wallet_transactions(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    cursor: str | None = None,
):
    """List wallet transactions (newest first) with cursor pagination."""
    from app.db.models.ai import WalletTransaction

    query = (
        select(WalletTransaction)
        .where(WalletTransaction.tenant_id == tenant.id)
        .order_by(WalletTransaction.created_at.desc())
        .limit(limit + 1)
    )

    if cursor:
        try:
            cursor_id = uuid.UUID(cursor)
            # Get the created_at of the cursor transaction
            cursor_result = await db.execute(
                select(WalletTransaction.created_at).where(WalletTransaction.id == cursor_id)
            )
            cursor_time = cursor_result.scalar_one_or_none()
            if cursor_time:
                query = query.where(WalletTransaction.created_at < cursor_time)
        except (ValueError, AttributeError):
            pass

    result = await db.execute(query)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = str(items[-1].id) if has_more and items else None

    return CursorPaginatedResponse(
        items=[WalletTransactionResponse.model_validate(t) for t in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )


# ── Prompt Templates ──────────────────────────────────────


@router.post(
    "/prompt-templates",
    response_model=PromptTemplateResponse,
    dependencies=[Depends(RequireScopes("ai:write"))],
    status_code=201,
)
async def create_prompt_template(
    body: PromptTemplateCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Create a reusable prompt template."""
    template = PromptTemplate(
        tenant_id=tenant.id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        variables=body.variables,
    )
    db.add(template)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Template named '{body.name}' already exists")
    await db.refresh(template)
    return PromptTemplateResponse.model_validate(template)


@router.get(
    "/prompt-templates",
    response_model=list[PromptTemplateResponse],
    dependencies=[Depends(RequireScopes("ai:read"))],
)
async def list_prompt_templates(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """List all prompt templates for the tenant."""
    result = await db.execute(
        select(PromptTemplate)
        .where(
            PromptTemplate.tenant_id == tenant.id,
            PromptTemplate.deleted_at.is_(None),
        )
        .order_by(PromptTemplate.created_at.desc())
    )
    return [PromptTemplateResponse.model_validate(t) for t in result.scalars().all()]


@router.put(
    "/prompt-templates/{template_id}",
    response_model=PromptTemplateResponse,
    dependencies=[Depends(RequireScopes("ai:write"))],
)
async def update_prompt_template(
    template_id: uuid.UUID,
    body: PromptTemplateUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Update a prompt template."""
    result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.id == template_id,
            PromptTemplate.tenant_id == tenant.id,
            PromptTemplate.deleted_at.is_(None),
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)

    await db.commit()
    await db.refresh(template)
    return PromptTemplateResponse.model_validate(template)


@router.delete(
    "/prompt-templates/{template_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("ai:admin"))],
)
async def delete_prompt_template(
    template_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a prompt template."""
    result = await db.execute(
        select(PromptTemplate).where(
            PromptTemplate.id == template_id,
            PromptTemplate.tenant_id == tenant.id,
            PromptTemplate.deleted_at.is_(None),
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    template.deleted_at = datetime.now(UTC)
    await db.commit()


# ── Usage Stats ───────────────────────────────────────────


@router.get(
    "/usage",
    response_model=AIUsageResponse,
    dependencies=[Depends(RequireScopes("ai:read"))],
)
async def get_usage_stats(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    days: int = 30,
):
    """Get AI usage statistics for the current tenant."""
    period_start = datetime.now(UTC) - timedelta(days=days)
    period_end = datetime.now(UTC)

    # Aggregate totals
    totals = await db.execute(
        select(
            func.count(AIUsageLog.id).label("total_requests"),
            func.coalesce(func.sum(AIUsageLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(AIUsageLog.prompt_tokens), 0).label("total_prompt_tokens"),
            func.coalesce(func.sum(AIUsageLog.completion_tokens), 0).label("total_completion_tokens"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("total_cost_usd"),
        ).where(
            AIUsageLog.tenant_id == tenant.id,
            AIUsageLog.created_at >= period_start,
        )
    )
    row = totals.one()

    # Aggregate by model
    by_model_result = await db.execute(
        select(
            AIUsageLog.model,
            AIUsageLog.provider,
            func.count(AIUsageLog.id).label("request_count"),
            func.coalesce(func.sum(AIUsageLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(AIUsageLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AIUsageLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("total_cost_usd"),
        )
        .where(
            AIUsageLog.tenant_id == tenant.id,
            AIUsageLog.created_at >= period_start,
        )
        .group_by(AIUsageLog.model, AIUsageLog.provider)
        .order_by(func.sum(AIUsageLog.total_tokens).desc())
    )

    by_model = [
        ModelUsageSummary(
            model=r.model,
            provider=r.provider,
            request_count=r.request_count,
            total_tokens=int(r.total_tokens),
            prompt_tokens=int(r.prompt_tokens),
            completion_tokens=int(r.completion_tokens),
            total_cost_usd=float(r.total_cost_usd),
        )
        for r in by_model_result.all()
    ]

    return AIUsageResponse(
        total_requests=row.total_requests,
        total_tokens=int(row.total_tokens),
        total_prompt_tokens=int(row.total_prompt_tokens),
        total_completion_tokens=int(row.total_completion_tokens),
        total_cost_usd=float(row.total_cost_usd),
        by_model=by_model,
        period_start=period_start,
        period_end=period_end,
    )
