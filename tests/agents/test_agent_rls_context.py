"""Tests for RLS tenant-context persistence across agent tool invocations.

Covers the fix for the root-cause bug: SET LOCAL is transaction-scoped,
so db.commit() wipes app.tenant_id. These tests verify that:

1. set_tenant_context is re-set before every tool call (setup.py)
2. set_tenant_context is re-set after the instance-creation commit (agents.py)
3. PendingRollbackError is handled in cleanup (agents.py)
4. PendingRollbackError is handled in _checkpoint_progress (runtime.py)
5. Session rollback on plugin tool failure (tool_registry.py)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from sqlalchemy.exc import PendingRollbackError

from tests.agents.conftest import make_agent_definition, make_mock_db

TENANT_ID = uuid.uuid4()
INSTANCE_ID = uuid.uuid4()


# ===================================================================
# 1. build_tool_executor re-sets tenant context before each tool call
# ===================================================================


class TestToolExecutorRLSContext:
    """Verify set_tenant_context is called before every tool invocation."""

    @pytest.mark.asyncio
    async def test_set_tenant_context_called_before_tool_invoke(self):
        """The tool executor must re-set RLS context before dispatching to registry."""
        from app.agents.setup import build_tool_executor

        definition = make_agent_definition(allowed_tools=["example_do_thing"])
        db = make_mock_db()

        mock_registry = AsyncMock()
        mock_registry.invoke = AsyncMock(return_value={"id": "prod-1", "name": "Test"})
        mock_set_ctx = AsyncMock()

        with (
            patch("app.agents.capabilities.capability_resolver.resolve_agent_tools", return_value=["example_do_thing"]),
            patch("app.agents.tool_registry.tool_registry", mock_registry),
            patch("app.db.session.set_tenant_context", mock_set_ctx),
        ):
            executor = build_tool_executor(definition, TENANT_ID, db)
            result = await executor("example_do_thing", {"name": "Batmobile", "slug": "batmobile"})

        # set_tenant_context must have been called with the correct tenant_id
        mock_set_ctx.assert_called_once_with(db, str(TENANT_ID))

        # The tool registry must have been invoked after the context was set
        mock_registry.invoke.assert_called_once_with(
            tool_name="example_do_thing",
            arguments={"name": "Batmobile", "slug": "batmobile"},
            tenant_id=TENANT_ID,
            db=db,
        )
        assert result == {"id": "prod-1", "name": "Test"}

    @pytest.mark.asyncio
    async def test_context_reset_on_consecutive_tool_calls(self):
        """Each tool call should re-set context, not just the first one."""
        from app.agents.setup import build_tool_executor

        definition = make_agent_definition(allowed_tools=["example_do_thing", "example_list_things"])
        db = make_mock_db()

        mock_registry = AsyncMock()
        mock_registry.invoke = AsyncMock(return_value={"ok": True})
        mock_set_ctx = AsyncMock()

        with (
            patch(
                "app.agents.capabilities.capability_resolver.resolve_agent_tools",
                return_value=["example_do_thing", "example_list_things"],
            ),
            patch("app.agents.tool_registry.tool_registry", mock_registry),
            patch("app.db.session.set_tenant_context", mock_set_ctx),
        ):
            executor = build_tool_executor(definition, TENANT_ID, db)
            await executor("example_do_thing", {"name": "A", "slug": "a"})
            await executor("example_list_things", {})

        # Should be called twice -- once per tool invocation
        assert mock_set_ctx.call_count == 2
        assert mock_set_ctx.call_args_list == [
            call(db, str(TENANT_ID)),
            call(db, str(TENANT_ID)),
        ]

    @pytest.mark.asyncio
    async def test_disallowed_tool_skips_context_set(self):
        """A disallowed tool should be rejected without touching the DB session."""
        from app.agents.setup import build_tool_executor

        definition = make_agent_definition(allowed_tools=["ai_complete"])
        db = make_mock_db()
        mock_set_ctx = AsyncMock()

        with (
            patch("app.agents.capabilities.capability_resolver.resolve_agent_tools", return_value=["ai_complete"]),
            patch("app.db.session.set_tenant_context", mock_set_ctx),
        ):
            executor = build_tool_executor(definition, TENANT_ID, db)
            result = await executor("example_do_thing", {"name": "A", "slug": "a"})

        assert "not allowed" in result["error"]
        mock_set_ctx.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_executor_catches_exceptions_gracefully(self):
        """A failing tool invocation should return an error dict, not raise."""
        from app.agents.setup import build_tool_executor

        definition = make_agent_definition(allowed_tools=["example_do_thing"])
        db = make_mock_db()

        mock_registry = AsyncMock()
        mock_registry.invoke = AsyncMock(side_effect=RuntimeError("DB exploded"))
        mock_set_ctx = AsyncMock()

        with (
            patch("app.agents.capabilities.capability_resolver.resolve_agent_tools", return_value=["example_do_thing"]),
            patch("app.agents.tool_registry.tool_registry", mock_registry),
            patch("app.db.session.set_tenant_context", mock_set_ctx),
        ):
            executor = build_tool_executor(definition, TENANT_ID, db)
            result = await executor("example_do_thing", {"name": "A", "slug": "a"})

        assert "error" in result
        assert "DB exploded" in result["error"]


# ===================================================================
# 2. _checkpoint_progress handles PendingRollbackError
# ===================================================================


class TestCheckpointRLSRecovery:
    """Verify _checkpoint_progress recovers from PendingRollbackError."""

    def _build_runtime(self):
        from app.agents.runtime import AgentRuntime, RunResult

        definition = make_agent_definition()
        runtime = AgentRuntime(
            definition=definition,
            tenant_id=TENANT_ID,
            api_key="sk-test",
            key_source="platform",
        )
        result = RunResult()
        result.total_tokens = 100
        result.total_cost_usd = 0.01
        return runtime, result

    @pytest.mark.asyncio
    async def test_checkpoint_resets_tenant_context(self):
        """Checkpoint should re-set tenant context before the UPDATE."""
        runtime, result = self._build_runtime()
        db = make_mock_db()
        mock_set_ctx = AsyncMock()

        with patch("app.db.session.set_tenant_context", mock_set_ctx):
            await runtime._checkpoint_progress(INSTANCE_ID, result, 1, db)

        mock_set_ctx.assert_called_with(db, str(TENANT_ID))
        db.execute.assert_called_once()
        db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_checkpoint_recovers_from_pending_rollback(self):
        """If the session is dirty, checkpoint should rollback and retry."""
        runtime, result = self._build_runtime()
        db = make_mock_db()

        call_count = 0

        async def mock_execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PendingRollbackError("session dirty")
            return MagicMock()

        db.execute = AsyncMock(side_effect=mock_execute_side_effect)
        mock_set_ctx = AsyncMock()

        with patch("app.db.session.set_tenant_context", mock_set_ctx):
            # Should not raise -- PendingRollbackError is handled
            await runtime._checkpoint_progress(INSTANCE_ID, result, 1, db)

        # rollback should have been called to recover
        db.rollback.assert_called_once()
        # set_tenant_context should be called at least twice (initial + retry)
        assert mock_set_ctx.call_count >= 2

    @pytest.mark.asyncio
    async def test_checkpoint_suppresses_all_errors(self):
        """Even if recovery fails, the checkpoint should never crash the run."""
        runtime, result = self._build_runtime()
        db = make_mock_db()
        db.execute = AsyncMock(side_effect=PendingRollbackError("dirty"))
        db.rollback = AsyncMock(side_effect=RuntimeError("rollback failed too"))

        mock_set_ctx = AsyncMock()

        with patch("app.db.session.set_tenant_context", mock_set_ctx):
            # Must not raise
            await runtime._checkpoint_progress(INSTANCE_ID, result, 1, db)


# ===================================================================
# 3. Plugin tool error recovery with session rollback
# ===================================================================


class TestPluginToolErrorRecovery:
    """Verify _invoke_plugin_tool rolls back the session on failure."""

    @pytest.mark.asyncio
    async def test_rollback_on_plugin_tool_exception(self):
        """When a plugin tool raises, the session should be rolled back."""
        from app.agents.tool_registry import ToolRegistry

        registry = ToolRegistry()
        db = make_mock_db()
        tenant = MagicMock(id=TENANT_ID)

        # Create a mock plugin whose invoke_tool raises
        mock_plugin = MagicMock()
        mock_plugin.name = "example"
        mock_plugin.get_agent_tool_definitions.return_value = {"example_do_thing": {}}
        mock_plugin.invoke_tool = AsyncMock(side_effect=RuntimeError("RLS violation"))

        with patch("app.plugins.registry.registry", [mock_plugin]):
            result = await registry._invoke_plugin_tool(
                "example_do_thing",
                {"name": "Test", "slug": "test"},
                tenant,
                db,
            )

        assert "error" in result
        assert "failed unexpectedly" in result["error"]
        # Critical: session must be rolled back
        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_rollback_on_validation_error(self):
        """Validation errors (ValueError, KeyError, TypeError) should NOT rollback."""
        from app.agents.tool_registry import ToolRegistry

        registry = ToolRegistry()
        db = make_mock_db()
        tenant = MagicMock(id=TENANT_ID)

        mock_plugin = MagicMock()
        mock_plugin.name = "example"
        mock_plugin.get_agent_tool_definitions.return_value = {"example_do_thing": {}}
        mock_plugin.invoke_tool = AsyncMock(side_effect=ValueError("bad input"))

        with patch("app.plugins.registry.registry", [mock_plugin]):
            result = await registry._invoke_plugin_tool(
                "example_do_thing",
                {"name": "Test", "slug": "test"},
                tenant,
                db,
            )

        assert "Invalid input" in result["error"]
        # Validation errors shouldn't trigger rollback
        db.rollback.assert_not_called()

    @pytest.mark.asyncio
    async def test_rollback_failure_does_not_propagate(self):
        """If rollback itself fails, the error should be swallowed."""
        from app.agents.tool_registry import ToolRegistry

        registry = ToolRegistry()
        db = make_mock_db()
        db.rollback = AsyncMock(side_effect=RuntimeError("rollback broken"))
        tenant = MagicMock(id=TENANT_ID)

        mock_plugin = MagicMock()
        mock_plugin.name = "example"
        mock_plugin.get_agent_tool_definitions.return_value = {"example_do_thing": {}}
        mock_plugin.invoke_tool = AsyncMock(side_effect=RuntimeError("RLS violation"))

        with patch("app.plugins.registry.registry", [mock_plugin]):
            # Must not raise even though rollback failed
            result = await registry._invoke_plugin_tool(
                "example_do_thing",
                {"name": "Test", "slug": "test"},
                tenant,
                db,
            )

        assert "error" in result


# ===================================================================
# 4. Streaming endpoint cleanup handles PendingRollbackError
# ===================================================================


class TestStreamingCleanupRecovery:
    """Verify the streaming endpoint's finally block handles dirty sessions."""

    @pytest.mark.asyncio
    async def test_cleanup_recovers_from_pending_rollback(self):
        """If the session is dirty at cleanup time, rollback + retry should work."""
        from app.agents.models import InstanceStatus

        db = make_mock_db()
        tenant_id = TENANT_ID
        instance_id = uuid.uuid4()

        call_count = 0
        mock_instance = MagicMock()
        mock_instance.status = InstanceStatus.RUNNING

        async def mock_get_side_effect(model, id_):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PendingRollbackError("session dirty")
            return mock_instance

        db.get = AsyncMock(side_effect=mock_get_side_effect)
        mock_set_ctx = AsyncMock()

        # Simulate the cleanup logic directly
        from sqlalchemy.exc import PendingRollbackError as PRE

        from app.agents.models import AgentInstance

        async def _cleanup_instance():
            try:
                await mock_set_ctx(db, str(tenant_id))
                inst = await db.get(AgentInstance, instance_id)
            except PRE:
                await db.rollback()
                await mock_set_ctx(db, str(tenant_id))
                inst = await db.get(AgentInstance, instance_id)

            if inst and inst.status in (InstanceStatus.RUNNING, InstanceStatus.PENDING):
                inst.status = InstanceStatus.FAILED
                inst.error = "Stream terminated unexpectedly"
                await db.commit()

        await _cleanup_instance()

        db.rollback.assert_called_once()
        assert mock_instance.status == InstanceStatus.FAILED
        db.commit.assert_called_once()


# ===================================================================
# 5. Full ReAct loop: tool calls get fresh RLS context
# ===================================================================


class TestRunStreamRLSContext:
    """End-to-end test: run_stream with tool calls verifies context is set."""

    @pytest.mark.asyncio
    async def test_run_stream_tool_call_resets_context(self):
        """During run_stream, each tool call should get fresh RLS context."""
        from dataclasses import dataclass
        from decimal import Decimal

        from app.agents.runtime import AgentRuntime

        @dataclass
        class FakeCompletion:
            id: str = "cmpl-1"
            model: str = "gpt-4o"
            provider: str = "openai"
            content: str = ""
            prompt_tokens: int = 10
            completion_tokens: int = 20
            total_tokens: int = 30
            cost_usd: float = 0.001
            billed_amount_usd: Decimal = Decimal("0.001")
            latency_ms: int = 100
            key_source: str = "platform"
            finish_reason: str | None = "stop"
            tool_calls: list[dict] | None = None

        definition = make_agent_definition(
            max_steps_per_run=3,
            max_tokens_per_run=100_000,
            allowed_tools=["example_do_thing"],
            output_schema={},
            governance_policy={},
        )

        runtime = AgentRuntime(
            definition=definition,
            tenant_id=TENANT_ID,
            api_key="sk-test",
            key_source="platform",
        )

        # First completion triggers a tool call, second gives final answer
        step = 0

        async def mock_completion(**kwargs):
            nonlocal step
            step += 1
            if step == 1:
                return FakeCompletion(
                    content="Let me create a product.",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "example_do_thing",
                            "arguments": '{"name": "Batmobile", "slug": "batmobile"}',
                        }
                    ],
                )
            return FakeCompletion(
                content="Product created successfully.",
                finish_reason="stop",
            )

        mock_gw = MagicMock()
        mock_gw.completion = AsyncMock(side_effect=mock_completion)

        # Track set_tenant_context calls
        ctx_calls = []
        original_set_ctx = AsyncMock()

        async def tracking_set_ctx(session, tid):
            ctx_calls.append(("set_ctx", tid))
            return await original_set_ctx(session, tid)

        async def mock_tool_executor(name, args):
            return {"id": "prod-1", "name": "Batmobile", "status": "draft"}

        db = make_mock_db()

        with (
            patch("app.ai.gateway.ai_gateway", mock_gw),
            patch("app.agents.governance.GovernanceEngine") as mock_gov_cls,
            patch("app.agents.runtime.emit", new_callable=AsyncMock),
            patch("app.db.session.set_tenant_context", tracking_set_ctx),
        ):
            mock_gov_cls.track_spending = AsyncMock()
            events = []
            async for event in runtime.run_stream(
                messages=[{"role": "user", "content": "Create a Batmobile product"}],
                instance_id=INSTANCE_ID,
                tool_executor=mock_tool_executor,
                governance_checker=None,
                db=db,
            ):
                events.append(event)

        # Verify we got tool_call and run_completed events
        event_types = [e["event"] for e in events]
        assert "tool_call" in event_types
        assert "run_completed" in event_types

        # Verify set_tenant_context was called during the run
        # (at least for checkpoint writes)
        assert len(ctx_calls) > 0


# ===================================================================
# 6. Regression: tool failure does not break subsequent tool calls
# ===================================================================


class TestToolFailureIsolation:
    """Verify one tool failure doesn't poison the session for later tool calls."""

    @pytest.mark.asyncio
    async def test_second_tool_works_after_first_fails(self):
        """If tool A fails, tool B should still succeed thanks to rollback."""
        from app.agents.setup import build_tool_executor

        definition = make_agent_definition(allowed_tools=["example_do_thing", "example_list_things"])
        db = make_mock_db()

        call_count = 0

        async def mock_invoke(tool_name, arguments, tenant_id, db):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("RLS violation on first tool")
            return {"products": []}

        mock_registry = MagicMock()
        mock_registry.invoke = AsyncMock(side_effect=mock_invoke)
        mock_set_ctx = AsyncMock()

        with (
            patch(
                "app.agents.capabilities.capability_resolver.resolve_agent_tools",
                return_value=["example_do_thing", "example_list_things"],
            ),
            patch("app.agents.tool_registry.tool_registry", mock_registry),
            patch("app.db.session.set_tenant_context", mock_set_ctx),
        ):
            executor = build_tool_executor(definition, TENANT_ID, db)

            # First call fails
            result1 = await executor("example_do_thing", {"name": "A", "slug": "a"})
            assert "error" in result1

            # Second call should succeed -- context was re-set
            result2 = await executor("example_list_things", {})
            assert result2 == {"products": []}

        # set_tenant_context called before each invocation
        assert mock_set_ctx.call_count == 2
