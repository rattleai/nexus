"""Tests for OpenAPI schema enrichment."""

from app.api.openapi_enrichment import enrich_openapi_schema


def test_enrich_adds_agent_compatible_flag():
    schema = {"info": {"title": "Test"}, "paths": {}}
    result = enrich_openapi_schema(schema)
    assert result["info"]["x-agent-compatible"] is True
    assert result["info"]["x-mcp-server"] == "nxs-mcp"


def test_enrich_adds_auth_methods():
    schema = {"info": {}, "paths": {}}
    result = enrich_openapi_schema(schema)
    assert "api-key" in result["info"]["x-auth-methods"]
    assert "oauth-client-credentials" in result["info"]["x-auth-methods"]


def test_enrich_adds_agent_hints_to_completions():
    schema = {
        "info": {},
        "paths": {
            "/api/v1/ai/completions": {
                "post": {
                    "summary": "Create completion",
                }
            }
        },
    }
    result = enrich_openapi_schema(schema)
    post_op = result["paths"]["/api/v1/ai/completions"]["post"]
    assert "x-agent-hint" in post_op
    assert "x-idempotent" in post_op
    assert post_op["x-idempotent"] is False


def test_enrich_adds_idempotent_marker_to_jobs():
    schema = {
        "info": {},
        "paths": {
            "/api/v1/jobs": {
                "post": {"summary": "Create job"},
                "get": {"summary": "List jobs"},
            }
        },
    }
    result = enrich_openapi_schema(schema)
    assert result["paths"]["/api/v1/jobs"]["post"].get("x-idempotent") is True
    assert "x-agent-hint" in result["paths"]["/api/v1/jobs"]["get"]


def test_enrich_preserves_existing_fields():
    schema = {
        "info": {"title": "Test", "version": "1.0"},
        "paths": {
            "/api/v1/health/live": {
                "get": {
                    "summary": "Liveness check",
                    "responses": {"200": {}},
                }
            }
        },
    }
    result = enrich_openapi_schema(schema)
    get_op = result["paths"]["/api/v1/health/live"]["get"]
    assert get_op["summary"] == "Liveness check"
    assert "responses" in get_op
    assert "x-agent-hint" in get_op
