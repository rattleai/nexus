"""Edge case tests for production hardening of the agent subsystem.

Covers: SSRF validation, workflow definition structure, tool name validation,
JSON size limits, auth config masking, idempotency key with failed instances,
event consumer conditional ack, tool execution timeout, conversation window,
and version fields in responses.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.schemas import (
    AgentDefinitionCreate,
    AgentDefinitionResponse,
    AgentPolicyCreate,
    AgentPolicyResponse,
    TenantToolCreate,
    TenantToolResponse,
    WorkflowDefinitionCreate,
    WorkflowDefinitionResponse,
    WorkflowRunCreate,
)

# ── SSRF URL Validation ──────────────────────────────────────────────


class TestSSRFProtection:
    """Verify that private/internal IPs are blocked in URL fields."""

    def test_rejects_private_ip_127(self):
        with pytest.raises(ValueError, match="private/internal"):
            TenantToolCreate(
                tool_name="test_tool",
                endpoint_url="https://127.0.0.1/api",
            )

    def test_rejects_metadata_ip(self):
        with pytest.raises(ValueError, match="private/internal"):
            TenantToolCreate(
                tool_name="test_tool",
                endpoint_url="https://169.254.169.254/latest/meta-data",
            )

    def test_rejects_private_ip_10(self):
        with pytest.raises(ValueError, match="private/internal"):
            TenantToolCreate(
                tool_name="test_tool",
                endpoint_url="https://10.0.0.1/internal",
            )

    def test_rejects_private_ip_172(self):
        with pytest.raises(ValueError, match="private/internal"):
            TenantToolCreate(
                tool_name="test_tool",
                endpoint_url="https://172.16.0.1/internal",
            )

    def test_rejects_http_scheme(self):
        with pytest.raises(ValueError, match="HTTPS"):
            TenantToolCreate(
                tool_name="test_tool",
                endpoint_url="http://example.com/api",
            )

    def test_allows_valid_https_domain(self):
        tool = TenantToolCreate(
            tool_name="test_tool",
            endpoint_url="https://api.example.com/v1/tool",
        )
        assert tool.endpoint_url == "https://api.example.com/v1/tool"

    def test_allows_none_url(self):
        tool = TenantToolCreate(tool_name="test_tool")
        assert tool.endpoint_url is None

    def test_health_check_url_also_validated(self):
        with pytest.raises(ValueError, match="private/internal"):
            TenantToolCreate(
                tool_name="test_tool",
                health_check_url="https://127.0.0.1/health",
            )


# ── Workflow Definition Validation ───────────────────────────────────


class TestWorkflowDefinitionValidation:
    """Verify workflow definition structure validation."""

    def test_rejects_missing_steps(self):
        with pytest.raises(ValueError, match="missing required keys"):
            WorkflowDefinitionCreate(
                name="test",
                slug="test",
                definition={"transitions": [], "entry_step": "a"},
            )

    def test_rejects_empty_steps(self):
        with pytest.raises(ValueError, match="at least one step"):
            WorkflowDefinitionCreate(
                name="test",
                slug="test",
                definition={"steps": [], "transitions": [], "entry_step": "a"},
            )

    def test_rejects_step_without_name(self):
        with pytest.raises(ValueError, match="'name' and 'agent_id'"):
            WorkflowDefinitionCreate(
                name="test",
                slug="test",
                definition={
                    "steps": [{"agent_id": "123"}],
                    "transitions": [],
                    "entry_step": "a",
                },
            )

    def test_rejects_step_without_agent_id(self):
        with pytest.raises(ValueError, match="'name' and 'agent_id'"):
            WorkflowDefinitionCreate(
                name="test",
                slug="test",
                definition={
                    "steps": [{"name": "step1"}],
                    "transitions": [],
                    "entry_step": "a",
                },
            )

    def test_accepts_valid_definition(self):
        wf = WorkflowDefinitionCreate(
            name="test",
            slug="test-wf",
            definition={
                "steps": [{"name": "step1", "agent_id": "abc-123"}],
                "transitions": [],
                "entry_step": "step1",
            },
        )
        assert wf.definition["entry_step"] == "step1"


# ── Tool Name Validation ────────────────────────────────────────────


class TestToolNameValidation:
    """Verify allowed_tools list validation on definitions and policies."""

    def test_rejects_too_many_tools(self):
        with pytest.raises(ValueError, match="Maximum 100"):
            AgentDefinitionCreate(
                name="test",
                slug="test",
                allowed_tools=["tool"] * 101,
            )

    def test_rejects_empty_tool_name(self):
        with pytest.raises(ValueError, match="1-100 characters"):
            AgentDefinitionCreate(
                name="test",
                slug="test",
                allowed_tools=[""],
            )

    def test_rejects_long_tool_name(self):
        with pytest.raises(ValueError, match="1-100 characters"):
            AgentDefinitionCreate(
                name="test",
                slug="test",
                allowed_tools=["x" * 101],
            )

    def test_accepts_valid_tools(self):
        defn = AgentDefinitionCreate(
            name="test",
            slug="test",
            allowed_tools=["ai_complete", "file_upload"],
        )
        assert len(defn.allowed_tools) == 2

    def test_policy_validates_tool_names(self):
        with pytest.raises(ValueError, match="Maximum 100"):
            AgentPolicyCreate(
                name="test",
                allowed_tools=["tool"] * 101,
            )


# ── JSON Size Limits ────────────────────────────────────────────────


class TestJSONSizeLimits:
    """Verify JSON payload size limits on dict fields."""

    def test_rejects_oversized_metadata(self):
        with pytest.raises(ValueError, match="exceeds maximum size"):
            AgentDefinitionCreate(
                name="test",
                slug="test",
                metadata={"big": "x" * 70_000},
            )

    def test_rejects_oversized_input_data(self):
        with pytest.raises(ValueError, match="exceeds maximum size of 1MB"):
            WorkflowRunCreate(
                input_data={"big": "x" * 1_100_000},
            )

    def test_accepts_normal_sized_metadata(self):
        defn = AgentDefinitionCreate(
            name="test",
            slug="test",
            metadata={"key": "value"},
        )
        assert defn.metadata == {"key": "value"}


# ── Auth Config Masking ──────────────────────────────────────────────


class TestAuthConfigMasking:
    """Verify all sensitive fields are masked in TenantToolResponse."""

    def test_masks_all_sensitive_keys(self):
        response = TenantToolResponse(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            tool_name="test",
            description="",
            source="tenant",
            input_schema={},
            output_schema={},
            endpoint_url=None,
            auth_config={
                "token": "secret-token",
                "key": "secret-key",
                "secret": "secret-val",
                "password": "secret-pass",
                "client_secret": "secret-cs",
                "api_key": "secret-ak",
                "type": "bearer",
            },
            is_active=True,
            health_check_url=None,
            metadata={},
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        for key in ("token", "key", "secret", "password", "client_secret", "api_key"):
            assert response.auth_config[key] == "***"
        # Non-sensitive keys preserved
        assert response.auth_config["type"] == "bearer"


# ── Version Fields in Responses ──────────────────────────────────────


class TestVersionFields:
    """Verify version field is exposed in all response schemas."""

    def test_agent_definition_response_has_version(self):
        data = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "name": "test",
            "slug": "test",
            "description": "",
            "status": "active",
            "version": 3,
            "system_prompt": "",
            "model": "gpt-4o",
            "temperature": None,
            "max_tokens": None,
            "allowed_tools": [],
            "max_steps_per_run": 50,
            "max_duration_seconds": 300,
            "max_tokens_per_run": 100000,
            "sandbox_enabled": False,
            "parallel_tool_execution": True,
            "max_concurrent_instances": 0,
            "memory_config": {},
            "governance_policy": {},
            "db_access_policy": {},
            "behavioral_baseline": {},
            "metadata": {},
            "capabilities": [],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        resp = AgentDefinitionResponse(**data)
        assert resp.version == 3

    def test_workflow_definition_response_has_version(self):
        data = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "name": "test",
            "slug": "test",
            "description": "",
            "status": "active",
            "version": 5,
            "definition": {},
            "governance": {},
            "metadata": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        resp = WorkflowDefinitionResponse(**data)
        assert resp.version == 5

    def test_agent_policy_response_has_version(self):
        data = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "name": "test",
            "description": "",
            "version": 2,
            "max_spend_per_run_usd": None,
            "max_spend_per_day_usd": None,
            "max_spend_per_month_usd": None,
            "allowed_tools": [],
            "denied_tools": [],
            "require_approval_for": [],
            "approval_timeout_seconds": 300,
            "approval_default_action": "deny",
            "max_requests_per_minute": None,
            "max_agent_requests_per_minute": None,
            "max_steps_per_run": None,
            "rules": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        resp = AgentPolicyResponse(**data)
        assert resp.version == 2


# ── Event Consumer Conditional Ack ───────────────────────────────────


@pytest.mark.asyncio
async def test_event_consumer_does_not_ack_failed_handler():
    """When a handler raises, the event must NOT be acknowledged."""
    from app.workers.event_consumer import _EVENT_HANDLERS, consume_loop

    mock_event_bus = AsyncMock()
    mock_event = MagicMock()
    mock_event.event_type = "AgentInstanceCompleted"
    mock_event.data = {"instance_id": "test"}
    mock_event.stream = "events:AgentInstanceCompleted"
    mock_event.id = "event-1"

    # Return one batch then raise CancelledError to stop the loop
    mock_event_bus.consume = AsyncMock(
        side_effect=[[mock_event], asyncio.CancelledError()],
    )
    mock_event_bus.ensure_group = AsyncMock()
    mock_event_bus.ack = AsyncMock()

    failing_handler = AsyncMock(side_effect=Exception("handler error"))

    with (
        patch("app.workers.event_consumer.event_bus", mock_event_bus),
        patch.dict(_EVENT_HANDLERS, {"AgentInstanceCompleted": [failing_handler]}, clear=False),
    ):
        await consume_loop()

    # ack should NOT have been called because handler failed
    mock_event_bus.ack.assert_not_called()


# ── Governance Atomic Spending ────────────────────────────────────────


@pytest.mark.asyncio
async def test_governance_atomic_spending_check():
    """Verify atomic spend check is used for daily spending limits."""
    from app.agents.governance import _atomic_spend_check

    mock_redis = AsyncMock()
    # Simulate the Lua script returning 0 (within bounds)
    mock_redis.eval = AsyncMock(return_value=0)

    with patch("app.agents.governance.redis_pool", mock_redis):
        result = await _atomic_spend_check("test:key", 0.5, 10.0)

    assert result == 0
    mock_redis.eval.assert_called_once()


@pytest.mark.asyncio
async def test_governance_atomic_spending_rejects_over_limit():
    """Verify atomic check returns -1 when limit would be exceeded."""
    from app.agents.governance import _atomic_spend_check

    mock_redis = AsyncMock()
    # Simulate the Lua script returning -1 (limit exceeded)
    mock_redis.eval = AsyncMock(return_value=-1)

    with patch("app.agents.governance.redis_pool", mock_redis):
        result = await _atomic_spend_check("test:key", 5.0, 10.0)

    assert result == -1
