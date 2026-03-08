"""SSE streaming helper for AI completions.

Wraps LiteLLM's async streaming response into Server-Sent Events (SSE)
format compatible with the EventSource browser API and httpx streaming.

Includes client disconnect detection, resource cleanup, and a post-stream
callback for wallet deduction and usage logging.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
from decimal import Decimal
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app.ai.cost import calculate_billed_amount_usd
from app.ai.metrics import AI_STREAM_CHUNKS_TOTAL

logger = structlog.stdlib.get_logger()


async def sse_stream_response(
    litellm_stream,
    *,
    model: str,
    provider: str,
    key_source: str,
    request_id: str,
    start_time: float,
    request: Request | None = None,
    on_complete: Callable[..., Coroutine[Any, Any, None]] | None = None,
) -> StreamingResponse:
    """Wrap a LiteLLM async streaming generator as an SSE StreamingResponse.

    Args:
        litellm_stream: The async generator from LiteLLM.
        model: Model identifier.
        provider: Provider name.
        key_source: "byok" or "platform".
        request_id: Unique request identifier.
        start_time: time.monotonic() when the request started.
        request: Optional Starlette Request for disconnect detection.
        on_complete: Optional async callback(prompt_tokens, completion_tokens,
                     total_tokens, billed_amount_usd, cost_usd, latency_ms)
                     called after stream ends. Used for wallet deduction and usage logging.

    Emits:
      - data: {"id": ..., "delta": "..."} for each content chunk
      - data: {"type": "usage", ...} final usage statistics
      - data: [DONE] to signal stream end
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        total_content = ""
        prompt_tokens = 0
        completion_tokens = 0
        finish_reason = None
        client_disconnected = False
        cost_usd = 0.0

        try:
            async for chunk in litellm_stream:
                # Client disconnect detection
                if request is not None and await request.is_disconnected():
                    logger.info(
                        "sse_client_disconnected",
                        request_id=request_id,
                        model=model,
                        streamed_chars=len(total_content),
                    )
                    client_disconnected = True
                    break

                # Extract delta content
                delta = ""
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta.content or ""
                    finish_reason = chunk.choices[0].finish_reason

                # Extract usage from final chunk if available
                if hasattr(chunk, "usage") and chunk.usage:
                    prompt_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0

                if delta:
                    total_content += delta
                    chunk_data = {
                        "id": completion_id,
                        "delta": delta,
                        "finish_reason": finish_reason,
                    }
                    AI_STREAM_CHUNKS_TOTAL.labels(provider=provider, model=model).inc()
                    yield f"data: {json.dumps(chunk_data)}\n\n"

        except Exception as exc:
            error_data = {"type": "error", "error": "An error occurred during streaming. Please retry."}
            yield f"data: {json.dumps(error_data)}\n\n"
            logger.error("sse_stream_error", model=model, request_id=request_id, error=str(exc))
        finally:
            # Ensure the LiteLLM stream is properly closed
            if hasattr(litellm_stream, "aclose"):
                try:
                    await litellm_stream.aclose()
                except Exception:
                    pass

        # Estimate tokens if not provided by the final chunk
        if not completion_tokens and total_content:
            completion_tokens = max(len(total_content) // 4, 1)

        total_tokens = prompt_tokens + completion_tokens

        # For streaming, estimate cost using LiteLLM's cost_per_token
        try:
            import litellm as _litellm

            cost_usd = _litellm.completion_cost(
                model=model,
                prompt=str(prompt_tokens),
                completion=str(completion_tokens),
            )
        except Exception:
            cost_usd = 0.0

        billed_amount_usd = calculate_billed_amount_usd(cost_usd, key_source)
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Invoke the on_complete callback for wallet deduction and usage logging.
        # This runs regardless of client disconnect — the tokens were consumed.
        if on_complete is not None:
            try:
                await on_complete(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    billed_amount_usd=billed_amount_usd,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                )
            except Exception as cb_exc:
                logger.error(
                    "sse_on_complete_error",
                    request_id=request_id,
                    error=str(cb_exc),
                )

        if not client_disconnected:
            # Final usage event
            usage_data = {
                "type": "usage",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "billed_amount_usd": float(billed_amount_usd),
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
            }
            yield f"data: {json.dumps(usage_data)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )
