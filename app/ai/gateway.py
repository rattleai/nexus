"""Core AI gateway — unified multi-provider LLM interface.

Wraps LiteLLM with circuit breaker, retry, streaming, fallback chains,
cost tracking, and full observability. This is the central orchestrator
that all AI requests flow through.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

import litellm
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from decimal import Decimal

from app.ai.cost import calculate_billed_amount_usd, get_response_cost, get_response_tokens
from app.ai.events import AICompletionCompleted, AICompletionFailed, AICompletionRequested
from app.ai.guardrails import filter_output
from app.ai.metrics import (
    AI_BILLED_USD_TOTAL,
    AI_COST_USD_TOTAL,
    AI_FALLBACK_TOTAL,
    AI_LATENCY_SECONDS,
    AI_REQUESTS_TOTAL,
    AI_TOKENS_TOTAL,
)
from app.ai.providers import DEFAULT_FALLBACK_CHAINS, get_model_info
from app.config import settings
from app.core.circuit_breaker import CircuitBreaker
from app.core.events import emit

logger = structlog.stdlib.get_logger()

# Pre-configured circuit breaker for AI providers
ai_breaker = CircuitBreaker("ai", failure_threshold=5, recovery_timeout=120)

# Auth errors should NOT trip the circuit breaker (they are config issues, not provider outages)
_AUTH_ERROR_TYPES = (
    litellm.AuthenticationError,
    litellm.NotFoundError,
)

# Transient errors ARE retryable and should trip the circuit breaker
_TRANSIENT_ERROR_TYPES = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.InternalServerError,
)


@dataclass
class AICompletionResult:
    """Result of a non-streaming AI completion."""

    id: str
    model: str
    provider: str
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    billed_amount_usd: Decimal = Decimal("0")
    latency_ms: int = 0
    key_source: str = "platform"
    finish_reason: str | None = None
    tool_calls: list[dict] | None = None


class AIGatewayError(Exception):
    """Base exception for AI gateway errors."""

    def __init__(self, message: str, *, provider: str = "", model: str = "", retryable: bool = False):
        self.provider = provider
        self.model = model
        self.retryable = retryable
        super().__init__(message)


class AIAuthenticationError(AIGatewayError):
    """API key is invalid or expired. Not retryable — user must fix their key."""


class AIProviderUnavailableError(AIGatewayError):
    """All providers (primary + fallbacks) are unavailable."""


class AIGateway:
    """Production-grade AI gateway with circuit breaker, fallback, and observability."""

    async def completion(
        self,
        *,
        tenant_id: uuid.UUID,
        model: str,
        messages: list[dict],
        api_key: str,
        key_source: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        fallback_models: list[str] | None = None,
        request_id: str | None = None,
        tenant_settings: dict | None = None,
        db: AsyncSession | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> AICompletionResult:
        """Execute a non-streaming AI completion with full infrastructure integration.

        Flow:
        1. Emit AICompletionRequested event
        2. Check circuit breaker
        3. Call LiteLLM (with absolute timeout ceiling)
        4. On failure: try fallback models (skip auth errors — they won't resolve by switching models)
        5. Track tokens, cost, latency
        6. Apply output guardrails
        7. Emit AICompletionCompleted/Failed event
        8. Return result
        """
        request_id = request_id or uuid.uuid4().hex
        model_info = get_model_info(model)
        if not model_info:
            raise AIGatewayError(f"Unknown model: {model}", model=model)

        provider = model_info.provider.value

        # Emit request event
        await emit(AICompletionRequested(
            tenant_id=str(tenant_id),
            model=model,
            request_id=request_id,
        ))

        # Build model chain: primary + fallbacks
        models_to_try = [model]
        if settings.AI_DEFAULT_FALLBACK_ENABLED:
            if fallback_models:
                models_to_try.extend(fallback_models)
            elif model in DEFAULT_FALLBACK_CHAINS:
                models_to_try.extend(DEFAULT_FALLBACK_CHAINS[model])

        last_error: Exception | None = None

        for i, candidate_model in enumerate(models_to_try):
            candidate_info = get_model_info(candidate_model)
            if not candidate_info:
                continue

            candidate_provider = candidate_info.provider.value
            breaker_key = candidate_provider

            # Resolve API key per-candidate: fallback models may use different
            # providers (e.g. GPT-4o → Claude → Gemini), each needing its own key.
            candidate_api_key = api_key
            candidate_key_source = key_source
            if i > 0 and candidate_info.provider != model_info.provider and db is not None:
                try:
                    from app.ai.key_resolver import resolve_api_key as _resolve_key

                    candidate_api_key, candidate_key_source = await _resolve_key(
                        tenant_id, candidate_info.provider, db
                    )
                except Exception:
                    logger.warning(
                        "ai_fallback_key_resolve_failed",
                        provider=candidate_provider,
                        model=candidate_model,
                    )
                    continue

            # Check circuit breaker
            if ai_breaker.is_open(breaker_key):
                logger.warning(
                    "ai_circuit_open",
                    provider=candidate_provider,
                    model=candidate_model,
                )
                if i > 0:
                    AI_FALLBACK_TOTAL.labels(
                        primary_model=model,
                        fallback_model=candidate_model,
                        reason="circuit_open",
                    ).inc()
                continue

            try:
                # Absolute timeout ceiling — prevents hung connections
                result = await asyncio.wait_for(
                    self._call_litellm(
                        model_info=candidate_info,
                        api_key=candidate_api_key,
                        key_source=candidate_key_source,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        request_id=request_id,
                        tenant_settings=tenant_settings,
                        tools=tools,
                        tool_choice=tool_choice,
                    ),
                    timeout=settings.AI_REQUEST_TIMEOUT_SECONDS + 5,  # LiteLLM timeout + buffer
                )

                # Record success on circuit breaker
                ai_breaker.record_success(breaker_key)

                if i > 0:
                    AI_FALLBACK_TOTAL.labels(
                        primary_model=model,
                        fallback_model=candidate_model,
                        reason="primary_failed",
                    ).inc()

                # Emit completion event
                await emit(AICompletionCompleted(
                    tenant_id=str(tenant_id),
                    model=candidate_model,
                    provider=candidate_provider,
                    total_tokens=result.total_tokens,
                    billed_amount_usd=float(result.billed_amount_usd),
                    cost_usd=result.cost_usd,
                    latency_ms=result.latency_ms,
                    key_source=key_source,
                    request_id=request_id,
                ))

                return result

            except _AUTH_ERROR_TYPES as exc:
                # Auth errors: do NOT trip circuit breaker, do NOT try fallbacks
                # (switching models won't fix a bad API key)
                last_error = exc
                logger.warning(
                    "ai_auth_error",
                    model=candidate_model,
                    provider=candidate_provider,
                    error=str(exc),
                )
                AI_REQUESTS_TOTAL.labels(
                    provider=candidate_provider,
                    model=candidate_model,
                    status="auth_error",
                    key_source=key_source,
                ).inc()

                await emit(AICompletionFailed(
                    tenant_id=str(tenant_id),
                    model=model,
                    provider=candidate_provider,
                    error="Authentication failed",
                    request_id=request_id,
                ))
                raise AIAuthenticationError(
                    f"Authentication failed for provider '{candidate_provider}'. Check your API key.",
                    provider=candidate_provider,
                    model=candidate_model,
                ) from exc

            except (asyncio.TimeoutError, *_TRANSIENT_ERROR_TYPES) as exc:
                # Transient errors: trip circuit breaker, try fallbacks
                last_error = exc
                ai_breaker.record_failure(breaker_key)
                logger.warning(
                    "ai_completion_failed",
                    model=candidate_model,
                    provider=candidate_provider,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    attempt=i + 1,
                )
                AI_REQUESTS_TOTAL.labels(
                    provider=candidate_provider,
                    model=candidate_model,
                    status="error",
                    key_source=key_source,
                ).inc()

            except Exception as exc:
                # Unknown errors: trip circuit breaker, try fallbacks
                last_error = exc
                ai_breaker.record_failure(breaker_key)
                logger.error(
                    "ai_completion_unexpected_error",
                    model=candidate_model,
                    provider=candidate_provider,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    attempt=i + 1,
                )
                AI_REQUESTS_TOTAL.labels(
                    provider=candidate_provider,
                    model=candidate_model,
                    status="error",
                    key_source=key_source,
                ).inc()

        # All models exhausted
        error_msg = f"All AI providers unavailable for model '{model}'"
        if last_error:
            error_msg = f"{error_msg}: {last_error}"

        await emit(AICompletionFailed(
            tenant_id=str(tenant_id),
            model=model,
            provider=provider,
            error=str(last_error) if last_error else "all_providers_unavailable",
            request_id=request_id,
        ))

        raise AIProviderUnavailableError(
            error_msg, provider=provider, model=model, retryable=True,
        )

    async def streaming_completion(
        self,
        *,
        tenant_id: uuid.UUID,
        model: str,
        messages: list[dict],
        api_key: str,
        key_source: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        request_id: str | None = None,
    ):
        """Return a LiteLLM async streaming generator.

        Streaming does not use fallback chains (to avoid mid-stream switches).
        The caller (streaming.py) wraps this into SSE format.
        """
        request_id = request_id or uuid.uuid4().hex
        model_info = get_model_info(model)
        if not model_info:
            raise AIGatewayError(f"Unknown model: {model}", model=model)

        provider = model_info.provider.value
        breaker_key = provider

        if ai_breaker.is_open(breaker_key):
            raise AIProviderUnavailableError(
                f"Provider '{provider}' circuit breaker is open",
                provider=provider,
                model=model,
            )

        kwargs = self._build_litellm_kwargs(model_info, api_key, max_tokens, temperature, top_p)

        await emit(AICompletionRequested(
            tenant_id=str(tenant_id),
            model=model,
            request_id=request_id,
            stream=True,
        ))

        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=model_info.litellm_model,
                    messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                    timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
                    **kwargs,
                ),
                timeout=settings.AI_REQUEST_TIMEOUT_SECONDS + 5,
            )
            ai_breaker.record_success(breaker_key)

            AI_REQUESTS_TOTAL.labels(
                provider=provider, model=model, status="success", key_source=key_source
            ).inc()

            return response

        except _AUTH_ERROR_TYPES as exc:
            AI_REQUESTS_TOTAL.labels(
                provider=provider, model=model, status="auth_error", key_source=key_source
            ).inc()
            await emit(AICompletionFailed(
                tenant_id=str(tenant_id),
                model=model,
                provider=provider,
                error="Authentication failed",
                request_id=request_id,
            ))
            raise AIAuthenticationError(
                f"Authentication failed for provider '{provider}'. Check your API key.",
                provider=provider,
                model=model,
            ) from exc

        except Exception as exc:
            ai_breaker.record_failure(breaker_key)
            AI_REQUESTS_TOTAL.labels(
                provider=provider, model=model, status="error", key_source=key_source
            ).inc()
            await emit(AICompletionFailed(
                tenant_id=str(tenant_id),
                model=model,
                provider=provider,
                error=str(exc),
                request_id=request_id,
            ))
            raise AIGatewayError(
                f"Streaming failed: {exc}", provider=provider, model=model,
                retryable=isinstance(exc, (*_TRANSIENT_ERROR_TYPES, asyncio.TimeoutError)),
            ) from exc

    async def _call_litellm(
        self,
        *,
        model_info,
        api_key: str,
        key_source: str,
        messages: list[dict],
        max_tokens: int | None,
        temperature: float | None,
        top_p: float | None,
        request_id: str,
        tenant_settings: dict | None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> AICompletionResult:
        """Execute a single LiteLLM call and process the response."""
        provider = model_info.provider.value
        model = model_info.litellm_model
        start = time.monotonic()

        kwargs = self._build_litellm_kwargs(model_info, api_key, max_tokens, temperature, top_p)

        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        response = await litellm.acompletion(
            model=model,
            messages=messages,
            stream=False,
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )

        elapsed = time.monotonic() - start
        latency_ms = int(elapsed * 1000)

        # Extract response data
        content = ""
        finish_reason = None
        raw_tool_calls = None
        if response.choices:
            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = choice.finish_reason

            # Extract tool calls from LLM response
            if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
                import json as _json
                raw_tool_calls = []
                for tc in choice.message.tool_calls:
                    args = tc.function.arguments
                    if isinstance(args, str):
                        try:
                            args = _json.loads(args)
                        except (_json.JSONDecodeError, TypeError):
                            args = {}
                    raw_tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })

        prompt_tokens, completion_tokens, total_tokens = get_response_tokens(response)
        cost_usd = get_response_cost(response)
        billed_amount_usd = calculate_billed_amount_usd(cost_usd, key_source)

        # Apply output guardrails
        content = filter_output(content, tenant_settings=tenant_settings)

        # Record Prometheus metrics
        AI_REQUESTS_TOTAL.labels(
            provider=provider, model=model_info.litellm_model, status="success", key_source=key_source
        ).inc()
        AI_TOKENS_TOTAL.labels(provider=provider, model=model_info.litellm_model, token_type="prompt").inc(prompt_tokens)
        AI_TOKENS_TOTAL.labels(provider=provider, model=model_info.litellm_model, token_type="completion").inc(completion_tokens)
        AI_BILLED_USD_TOTAL.labels(provider=provider, model=model_info.litellm_model, key_source=key_source).inc(float(billed_amount_usd))
        AI_LATENCY_SECONDS.labels(provider=provider, model=model_info.litellm_model).observe(elapsed)
        AI_COST_USD_TOTAL.labels(provider=provider, model=model_info.litellm_model).inc(cost_usd)

        completion_id = getattr(response, "id", None) or f"chatcmpl-{uuid.uuid4().hex[:12]}"

        return AICompletionResult(
            id=completion_id,
            model=model_info.litellm_model,
            provider=provider,
            content=content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            billed_amount_usd=billed_amount_usd,
            latency_ms=latency_ms,
            key_source=key_source,
            finish_reason=finish_reason,
            tool_calls=raw_tool_calls,
        )

    def _build_litellm_kwargs(
        self,
        model_info,
        api_key: str,
        max_tokens: int | None,
        temperature: float | None,
        top_p: float | None,
    ) -> dict:
        """Build kwargs dict for litellm.acompletion()."""
        kwargs: dict = {"api_key": api_key}

        if max_tokens is not None:
            kwargs["max_tokens"] = min(max_tokens, model_info.max_output_tokens)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p

        # Qwen requires a custom base URL
        if model_info.provider.value == "qwen":
            if settings.AI_QWEN_API_BASE:
                kwargs["api_base"] = settings.AI_QWEN_API_BASE

        return kwargs


# Module-level singleton
ai_gateway = AIGateway()
