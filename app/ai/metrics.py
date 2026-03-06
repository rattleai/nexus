"""Prometheus metrics for AI gateway observability."""

from prometheus_client import Counter, Gauge, Histogram

AI_REQUESTS_TOTAL = Counter(
    "saas_ai_requests_total",
    "Total AI completion requests",
    ["provider", "model", "status", "key_source"],
)

AI_TOKENS_TOTAL = Counter(
    "saas_ai_tokens_total",
    "Total tokens consumed by AI requests",
    ["provider", "model", "token_type"],  # token_type: prompt, completion
)

AI_BILLED_TOKENS_TOTAL = Counter(
    "saas_ai_billed_tokens_total",
    "Total billed tokens (with margin applied)",
    ["provider", "model", "key_source"],
)

AI_LATENCY_SECONDS = Histogram(
    "saas_ai_latency_seconds",
    "AI request latency in seconds",
    ["provider", "model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

AI_COST_USD_TOTAL = Counter(
    "saas_ai_cost_usd_total",
    "Total raw provider cost in USD",
    ["provider", "model"],
)

AI_WALLET_BALANCE = Gauge(
    "saas_ai_wallet_balance_tokens",
    "Current wallet balance in tokens",
    ["tenant_id"],
)

AI_STREAM_CHUNKS_TOTAL = Counter(
    "saas_ai_stream_chunks_total",
    "Total SSE chunks sent for streaming responses",
    ["provider", "model"],
)

AI_FALLBACK_TOTAL = Counter(
    "saas_ai_fallback_total",
    "Total times a fallback model was used",
    ["primary_model", "fallback_model", "reason"],
)
