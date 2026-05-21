"""Cost calculation with USD-based margin.

Uses LiteLLM's built-in cost tracking for provider costs (USD), then applies
platform margin based on key source (BYOK vs platform-managed).
"""

from __future__ import annotations

from decimal import ROUND_UP, Decimal

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()


def calculate_billed_amount_usd(provider_cost_usd: float, key_source: str) -> Decimal:
    """Apply platform margin to provider cost to get billed amount in USD.

    Args:
        provider_cost_usd: Raw cost from LiteLLM response._hidden_params["response_cost"].
        key_source: "byok" or "platform" — determines margin multiplier.

    Returns:
        Billed amount in USD (Decimal, 6 decimal places, rounded up).
    """
    if key_source == "byok":
        multiplier = Decimal(str(settings.AI_MARGIN_BYOK_KEYS))
    else:
        multiplier = Decimal(str(settings.AI_MARGIN_PLATFORM_KEYS))

    billed = Decimal(str(provider_cost_usd)) * multiplier
    return billed.quantize(Decimal("0.000001"), rounding=ROUND_UP)


def estimate_max_cost_usd(
    model: str,
    messages: list[dict],
    max_tokens: int | None,
    model_max_output: int,
    key_source: str = "platform",
) -> Decimal:
    """Estimate the maximum USD cost a request might incur (for wallet pre-check).

    Uses LiteLLM's cost_per_token() for the model to estimate worst-case cost,
    then applies margin. This is intentionally conservative.
    """
    try:
        import litellm

        prompt_cost, completion_cost = litellm.cost_per_token(model=model, prompt_tokens=1, completion_tokens=1)
    except Exception:
        # Fallback: use a conservative default ($0.01 per 1K tokens)
        prompt_cost = 0.00001
        completion_cost = 0.00003

    # Estimate input tokens (rough: 1 token ≈ 4 chars)
    input_chars = sum(len(m.get("content", "")) for m in messages)
    estimated_input = max(input_chars // 4, 1)

    # Output tokens: use requested max_tokens or a conservative default
    estimated_output = max_tokens or min(model_max_output, 4096)

    estimated_cost = (estimated_input * prompt_cost) + (estimated_output * completion_cost)

    return calculate_billed_amount_usd(estimated_cost, key_source)


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
