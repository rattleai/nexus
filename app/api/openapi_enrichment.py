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
