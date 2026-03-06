"""SSE streaming helper for AI completions.

Wraps LiteLLM's async streaming response into Server-Sent Events (SSE)
format compatible with the EventSource browser API and httpx streaming.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator

import structlog
from starlette.responses import StreamingResponse

from app.ai.cost import calculate_billed_tokens
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
) -> StreamingResponse:
    """Wrap a LiteLLM async streaming generator as an SSE StreamingResponse.

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

        try:
            async for chunk in litellm_stream:
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
            error_data = {"type": "error", "error": str(exc)}
            yield f"data: {json.dumps(error_data)}\n\n"
            logger.error("sse_stream_error", model=model, error=str(exc))
            yield "data: [DONE]\n\n"
            return

        # Estimate tokens if not provided by the final chunk
        if not completion_tokens:
            completion_tokens = max(len(total_content) // 4, 1)
        if not prompt_tokens:
            prompt_tokens = 0  # Will be filled from non-streaming metadata if available

        total_tokens = prompt_tokens + completion_tokens
        billed_tokens = calculate_billed_tokens(total_tokens, key_source)
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Final usage event
        usage_data = {
            "type": "usage",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "billed_tokens": billed_tokens,
            "cost_usd": 0.0,  # Streaming cost is approximated; exact cost available in usage logs
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
