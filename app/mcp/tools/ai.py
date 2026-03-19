"""MCP tools for AI operations."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.ai.gateway import AIAuthenticationError, AIGatewayError, AIProviderUnavailableError, ai_gateway
from app.ai.guardrails import validate_input
from app.ai.key_resolver import NoAPIKeyError, resolve_api_key
from app.ai.providers import MODEL_CATALOG, get_model_info
from app.ai.wallet import InsufficientBalanceError, wallet_service
from app.db.models.ai import AIUsageLog
from app.mcp.errors import insufficient_balance_error, tool_error

logger = structlog.stdlib.get_logger()


async def ai_complete(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    *,
    tenant: Any,
    db: Any,
) -> dict:
    """Run an AI completion. Returns the completion response.

    Use this to generate text with an AI model. Specify the model name
    and a list of messages (each with 'role' and 'content' keys).

    Example messages: [{"role": "user", "content": "Hello, how are you?"}]
    """
    # Validate messages structure
    if not messages:
        raise tool_error("Messages list cannot be empty.")
    if len(messages) > 200:
        raise tool_error("Too many messages (max 200).")
    valid_roles = {"user", "system", "assistant"}
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise tool_error(
                f"Message at index {i} must be a dict with 'role' and 'content' keys.",
            )
        if "role" not in msg or "content" not in msg:
            raise tool_error(
                f"Message at index {i} missing required keys.",
                hint="Each message needs 'role' (user/system/assistant) and 'content'.",
            )
        if msg["role"] not in valid_roles:
            raise tool_error(
                f"Invalid role '{msg['role']}' at index {i}.",
                hint=f"Valid roles: {', '.join(sorted(valid_roles))}",
            )

    # Validate numeric parameters
    if temperature is not None and not (0.0 <= temperature <= 2.0):
        raise tool_error(
            f"Temperature must be between 0.0 and 2.0, got {temperature}.",
        )
    if top_p is not None and not (0.0 <= top_p <= 1.0):
        raise tool_error(
            f"top_p must be between 0.0 and 1.0, got {top_p}.",
        )
    if max_tokens is not None and max_tokens < 1:
        raise tool_error("max_tokens must be at least 1.")

    model_info = get_model_info(model)
    if not model_info:
        raise tool_error(
            f"Unknown model: {model}",
            hint="Use ai_list_models to see available models.",
        )

    violations = validate_input(messages, tenant_settings=tenant.settings)
    if violations:
        raise tool_error(f"Input guardrail violation: {violations[0]}")

    try:
        api_key, key_source = await resolve_api_key(tenant.id, model_info.provider, db)
    except NoAPIKeyError as exc:
        raise tool_error(
            f"No API key available for provider '{model_info.provider.value}'",
            hint="Configure a BYOK key via the platform or contact the administrator.",
        ) from exc

    request_id = uuid.uuid4().hex

    try:
        result = await ai_gateway.completion(
            tenant_id=tenant.id,
            model=model,
            messages=messages,
            api_key=api_key,
            key_source=key_source,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            request_id=request_id,
            tenant_settings=tenant.settings,
            db=db,
        )
    except AIAuthenticationError as exc:
        raise tool_error(f"AI provider authentication failed: {exc}") from exc
    except AIProviderUnavailableError as exc:
        raise tool_error(f"AI provider unavailable: {exc}") from exc
    except AIGatewayError as exc:
        raise tool_error(f"AI gateway error: {exc}") from exc

    # Deduct from wallet
    try:
        await wallet_service.deduct_tokens(
            tenant.id,
            result.billed_tokens,
            description=f"AI completion: {model}",
            reference_id=request_id,
            db=db,
        )
    except InsufficientBalanceError as exc:
        raise insufficient_balance_error(exc.available) from exc

    # Log usage
    usage_log = AIUsageLog(
        tenant_id=tenant.id,
        provider=result.provider,
        model=model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        cost_usd=result.cost_usd,
        billed_amount_usd=result.cost_usd,
        latency_ms=result.latency_ms,
        status="success",
        key_source=result.key_source,
        request_id=request_id,
    )
    db.add(usage_log)
    await db.commit()

    return {
        "id": result.id,
        "model": result.model,
        "content": result.content,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "billed_amount_usd": float(result.billed_amount_usd),
        "latency_ms": result.latency_ms,
        "finish_reason": result.finish_reason,
    }


async def ai_list_models(*, tenant: Any, db: Any) -> list[dict]:
    """List all available AI models with their capabilities.

    Returns model IDs, providers, token limits, and feature support
    (streaming, function calling, vision). Use this to discover which
    models are available before calling ai_complete.
    """
    from app.ai.key_resolver import check_key_availability

    models = []
    for model_id, info in MODEL_CATALOG.items():
        if info.deprecated:
            continue

        available, _source = await check_key_availability(tenant.id, info.provider, db)

        models.append({
            "model_id": model_id,
            "provider": info.provider.value,
            "display_name": info.display_name,
            "max_input_tokens": info.max_input_tokens,
            "max_output_tokens": info.max_output_tokens,
            "supports_streaming": info.supports_streaming,
            "supports_function_calling": info.supports_function_calling,
            "supports_vision": info.supports_vision,
            "available": available,
        })

    return models


async def ai_get_usage(days: int = 30, *, tenant: Any, db: Any) -> dict:
    """Get AI usage statistics for the specified number of days.

    Returns total requests, token counts, cost, and per-model breakdown.
    Use this to monitor API consumption and costs.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    period_start = datetime.now(UTC) - timedelta(days=days)
    period_end = datetime.now(UTC)

    totals = await db.execute(
        select(
            func.count(AIUsageLog.id).label("total_requests"),
            func.coalesce(func.sum(AIUsageLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(AIUsageLog.prompt_tokens), 0).label("total_prompt_tokens"),
            func.coalesce(func.sum(AIUsageLog.completion_tokens), 0).label("total_completion_tokens"),
            func.coalesce(func.sum(AIUsageLog.billed_amount_usd), 0).label("total_billed_usd"),
        ).where(
            AIUsageLog.tenant_id == tenant.id,
            AIUsageLog.created_at >= period_start,
        )
    )
    row = totals.one()

    return {
        "total_requests": row.total_requests,
        "total_tokens": int(row.total_tokens),
        "total_prompt_tokens": int(row.total_prompt_tokens),
        "total_completion_tokens": int(row.total_completion_tokens),
        "total_billed_usd": float(row.total_billed_usd),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "days": days,
    }
