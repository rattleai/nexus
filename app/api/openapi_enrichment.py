"""OpenAPI schema enrichment for AI agent discovery.

Post-processes the FastAPI-generated OpenAPI schema to add richer descriptions,
agent hints, idempotency markers, and rate limit tier information.
"""

from __future__ import annotations

from typing import Any

# Endpoint-specific enrichments keyed by (method, path_suffix)
_ENRICHMENTS: dict[tuple[str, str], dict[str, Any]] = {
    ("post", "/ai/completions"): {
        "x-agent-hint": (
            "Primary endpoint for AI text generation. Supports sync and streaming (stream: true). "
            "Check wallet balance before calling. Use ai/models to discover available models."
        ),
        "x-idempotent": False,
    },
    ("post", "/ai/completions/async"): {
        "x-agent-hint": (
            "Submit AI completion for async processing. Returns a Job ID. "
            "Poll GET /api/v1/jobs/{id} for results."
        ),
        "x-idempotent": False,
    },
    ("get", "/ai/models"): {
        "x-agent-hint": "Discover available models, their capabilities, and availability status.",
    },
    ("get", "/ai/wallet/balance"): {
        "x-agent-hint": "Check token balance before making AI completions to avoid 402 errors.",
    },
    ("post", "/ai/wallet/topup"): {
        "x-agent-hint": "Requires ai:admin scope and a verified payment reference_id.",
        "x-idempotent": True,
    },
    ("get", "/ai/usage"): {
        "x-agent-hint": "Monitor AI consumption. Use 'days' param to adjust the reporting period.",
    },
    ("post", "/jobs"): {
        "x-agent-hint": "Create background jobs. Supports X-Idempotency-Key header for safe retries.",
        "x-idempotent": True,
    },
    ("get", "/jobs"): {
        "x-agent-hint": "List jobs with optional status filter. Supports cursor pagination.",
    },
    ("post", "/files"): {
        "x-agent-hint": "Upload files via multipart form. Max size configurable per plan.",
        "x-idempotent": False,
    },
    ("post", "/api-keys"): {
        "x-agent-hint": (
            "Create API keys with specific scopes. "
            "Store the returned key securely — it cannot be retrieved later."
        ),
        "x-idempotent": False,
    },
    # ── Team ──
    ("get", "/team/members"): {
        "x-agent-hint": "List team members with roles. Use to discover who has access.",
    },
    ("post", "/team/invite"): {
        "x-agent-hint": "Invite a new member by email. Requires team:write scope.",
        "x-idempotent": False,
    },
    # ── Webhooks ──
    ("get", "/webhooks"): {
        "x-agent-hint": "List configured webhook endpoints for event subscriptions.",
    },
    ("post", "/webhooks"): {
        "x-agent-hint": (
            "Create a webhook endpoint. URL must be HTTPS. "
            "Store the signing_secret to verify deliveries."
        ),
        "x-idempotent": False,
    },
    ("delete", "/webhooks/{webhook_id}"): {
        "x-agent-hint": "Delete a webhook endpoint by ID. Stops all event deliveries.",
    },
    # ── Billing ──
    ("get", "/billing/plans"): {
        "x-agent-hint": "List subscription plans with pricing. Compare before upgrading.",
    },
    ("get", "/billing/subscription"): {
        "x-agent-hint": "Get current subscription details and billing period.",
    },
    # ── Export ──
    ("post", "/export"): {
        "x-agent-hint": (
            "Request a GDPR data export. Returns an export ID. "
            "Poll GET /export/{id} for completion."
        ),
        "x-idempotent": False,
    },
    ("get", "/export/{export_id}"): {
        "x-agent-hint": "Check export status. Download URL available when status is 'completed'.",
    },
    # ── Auth ──
    ("post", "/oauth/token"): {
        "x-agent-hint": (
            "Exchange client_id + client_secret for a short-lived JWT. "
            "Rate limited to 10 requests/minute."
        ),
    },
    ("post", "/oauth/clients"): {
        "x-agent-hint": "Register an OAuth client for machine-to-machine auth. Admin only.",
        "x-idempotent": False,
    },
    # ── API Keys ──
    ("get", "/api-keys"): {
        "x-agent-hint": "List API keys for the tenant. Secrets are masked.",
    },
    ("delete", "/api-keys/{key_id}"): {
        "x-agent-hint": "Revoke an API key. Cannot be undone.",
    },
    # ── Files ──
    ("get", "/files"): {
        "x-agent-hint": "List uploaded files. Use prefix param to filter by path.",
    },
    # ── Batch ──
    ("post", "/batch"): {
        "x-agent-hint": (
            "Execute up to 10 sub-requests in a single call. "
            "Reduces round-trips for multi-step workflows."
        ),
    },
    # ── Health ──
    ("get", "/health/live"): {
        "x-agent-hint": "Lightweight liveness check. No auth required.",
    },
    ("get", "/health/ready"): {
        "x-agent-hint": "Readiness check including DB and Redis connectivity.",
    },
}


def enrich_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Enrich the OpenAPI schema with agent-friendly metadata.

    Adds:
    - x-agent-hint extensions on operations
    - x-idempotent markers on mutating endpoints
    - Richer descriptions where available
    """
    paths = schema.get("paths", {})

    for path, path_item in paths.items():
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if not operation:
                continue

            # Try to match by path suffix
            for (enrich_method, enrich_suffix), extensions in _ENRICHMENTS.items():
                if method == enrich_method and path.endswith(enrich_suffix):
                    for key, value in extensions.items():
                        operation[key] = value
                    break

    # Add server-level agent metadata
    schema.setdefault("info", {})
    schema["info"]["x-agent-compatible"] = True
    schema["info"]["x-mcp-server"] = "cadprice-mcp"
    schema["info"]["x-auth-methods"] = ["api-key", "oauth-client-credentials"]

    return schema
