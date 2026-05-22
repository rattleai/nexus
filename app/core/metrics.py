"""Custom Prometheus business metrics for SaaS platform observability.

Provides counters, histograms, and gauges for:
- Job processing throughput and latency
- Webhook delivery success/failure rates
- HTTP request rates by tenant
- Circuit breaker state changes

Import and use these metrics in the relevant code paths:
    from app.core.metrics import JOBS_TOTAL, JOB_DURATION
    JOBS_TOTAL.labels(status="completed", type="export").inc()
    JOB_DURATION.observe(elapsed_seconds)
"""

from prometheus_client import Counter, Gauge, Histogram

# ── Job metrics ──────────────────────────────────────────

JOBS_TOTAL = Counter(
    "saas_jobs_total",
    "Total jobs processed",
    ["status", "type"],
)

JOB_DURATION = Histogram(
    "saas_job_duration_seconds",
    "Job processing duration in seconds",
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300],
)

# ── Webhook metrics ──────────────────────────────────────

WEBHOOK_DELIVERIES_TOTAL = Counter(
    "saas_webhook_deliveries_total",
    "Total webhook delivery attempts",
    ["status"],  # delivered, failed, circuit_open
)

# ── Auth metrics ─────────────────────────────────────────

AUTH_ATTEMPTS_TOTAL = Counter(
    "saas_auth_attempts_total",
    "Authentication attempts",
    ["method", "result"],  # method=login|api_key, result=success|failure|lockout
)

# ── Circuit breaker metrics ──────────────────────────────

CIRCUIT_BREAKER_STATE = Gauge(
    "saas_circuit_breaker_open",
    "Whether a circuit breaker is currently open (1=open, 0=closed)",
    ["breaker", "key"],
)
