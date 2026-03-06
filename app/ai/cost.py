"""Token counting and cost calculation with tiered margin.

Uses LiteLLM's built-in cost tracking for provider costs, then applies
platform margin based on key source (BYOK vs platform-managed).
"""

from __future__ import annotations

import math

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


def calculate_billed_tokens(total_tokens: int, key_source: str) -> int:
    """Apply platform margin to raw token count based on key source.

    Args:
        total_tokens: Raw tokens consumed by the AI call.
        key_source: "byok" or "platform" — determines margin multiplier.

    Returns:
        Billed token count (always rounded up to prevent rounding loss).
    """
    if key_source == "byok":
        multiplier = settings.AI_MARGIN_BYOK_KEYS
    else:
        multiplier = settings.AI_MARGIN_PLATFORM_KEYS

    return math.ceil(total_tokens * multiplier)


def estimate_max_tokens(messages: list[dict], max_tokens: int | None, model_max_output: int) -> int:
    """Estimate the maximum tokens a request might consume (for wallet reservation).

    Uses a rough heuristic: ~4 chars per token for input, plus requested max_tokens for output.
    This is intentionally conservative to avoid over-reserving.
    """
    # Estimate input tokens (rough: 1 token ≈ 4 chars)
    input_chars = sum(len(m.get("content", "")) for m in messages)
    estimated_input = max(input_chars // 4, 1)

    # Output tokens: use requested max_tokens or a conservative default
    estimated_output = max_tokens or min(model_max_output, 4096)

    return estimated_input + estimated_output


def get_response_cost(response) -> float:
    """Extract cost in USD from a LiteLLM response.

    LiteLLM stores the cost in response._hidden_params["response_cost"].
    Falls back to 0.0 if not available.
    """
    try:
        hidden = getattr(response, "_hidden_params", {})
        if hidden and "response_cost" in hidden:
            return float(hidden["response_cost"])
    except Exception:
        logger.debug("cost_extraction_failed")
    return 0.0


def get_response_tokens(response) -> tuple[int, int, int]:
    """Extract token counts from a LiteLLM response.

    Returns:
        Tuple of (prompt_tokens, completion_tokens, total_tokens).
    """
    try:
        usage = response.usage
        if usage:
            prompt = getattr(usage, "prompt_tokens", 0) or 0
            completion = getattr(usage, "completion_tokens", 0) or 0
            total = getattr(usage, "total_tokens", 0) or (prompt + completion)
            return prompt, completion, total
    except Exception:
        logger.debug("token_extraction_failed")
    return 0, 0, 0
