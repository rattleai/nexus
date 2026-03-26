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

# ── Configurator metrics ────────────────────────────────

CONFIGURATOR_PROPAGATION_DURATION = Histogram(
    "configurator_propagation_seconds",
    "Constraint propagation duration in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
)

CONFIGURATOR_PROPAGATION_ITERATIONS = Histogram(
    "configurator_propagation_iterations",
    "Number of iterations in the constraint propagation loop",
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000],
)

CONFIGURATOR_BOM_RESOLUTION_DURATION = Histogram(
    "configurator_bom_resolution_seconds",
    "BOM resolution duration in seconds",
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
)

CONFIGURATOR_CONSTRAINT_EVALUATIONS = Counter(
    "configurator_constraint_evaluations_total",
    "Total constraint evaluations during propagation",
    ["constraint_type"],
)

CONFIGURATOR_CONTRADICTIONS = Counter(
    "configurator_contradictions_total",
    "Total contradictions detected during propagation",
)
