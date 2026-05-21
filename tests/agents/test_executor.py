"""Tests for AgentExecutor lifecycle — definition loading, session management,
error recovery, message truncation, and input validation.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.executor import AgentExecutionError, AgentExecutor
from app.agents.models import AgentStatus, InstanceStatus, SessionStatus
from app.agents.runtime import RunResult, StepResult
from tests.agents.conftest import make_agent_definition, make_mock_db

# ── Helpers ───────────────────────────────────────────────────────────


def _valid_input_data(prompt: str = "Hello") -> dict:
    return {"messages": [{"role": "user", "content": prompt}]}


def _make_session(**overrides) -> MagicMock:
    defaults = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "instance_id": uuid.uuid4(),
        "status": SessionStatus.ACTIVE,
        "messages": [],
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_run_result(**overrides) -> RunResult:
    defaults = {
        "output": "test output",
        "steps": [],
        "total_tokens": 100,
        "total_cost_usd": 0.001,
        "total_duration_ms": 500,
        "finish_reason": "completed",
    }
    defaults.update(overrides)
    return RunResult(**defaults)


def _build_executor_patches(
    *,
    definition=None,
    session=None,
    run_result=None,
):
    """Return a dict of common patches needed for AgentExecutor.run().

    Callers can override individual return values.
    """
    definition = definition if definition is not None else make_agent_definition()
    session = session if session is not None else _make_session()
    run_result = run_result if run_result is not None else _make_run_result()

    mock_runtime_instance = AsyncMock()
    mock_runtime_instance.run = AsyncMock(return_value=run_result)

    mock_runtime_cls = MagicMock(return_value=mock_runtime_instance)

    patches = {
        "set_tenant_context": patch(
            "app.agents.executor.set_tenant_context",
            new_callable=AsyncMock,
        ),
        "load_definition": patch.object(
            AgentExecutor,
            "_load_definition",
            new_callable=AsyncMock,
            return_value=definition,
        ),
        "get_or_create_session": patch.object(
            AgentExecutor,
            "_get_or_create_session",
            new_callable=AsyncMock,
            return_value=session,
        ),
        "runtime_cls": patch("app.agents.executor.AgentRuntime", mock_runtime_cls),
        "emit": patch("app.agents.executor.emit", new_callable=AsyncMock),
    }
    return patches, mock_runtime_cls, mock_runtime_instance


# ── 1. Definition not found / inactive ────────────────────────────────


class TestDefinitionValidation:
    @pytest.mark.asyncio
    async def test_run_raises_when_definition_not_found(self):
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=None,
            ),
            pytest.raises(AgentExecutionError, match="not found"),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
            )

    @pytest.mark.asyncio
    async def test_run_raises_when_definition_not_active(self):
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)
        inactive_def = make_agent_definition(status=AgentStatus.DRAFT)

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=inactive_def,
            ),
            pytest.raises(AgentExecutionError, match="not active"),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
            )

    @pytest.mark.asyncio
    async def test_run_raises_when_definition_disabled(self):
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)
        disabled_def = make_agent_definition(status=AgentStatus.DISABLED)

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=disabled_def,
            ),
            pytest.raises(AgentExecutionError, match="not active"),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
            )


# ── 2. Session creation and resumption ────────────────────────────────


class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_new_session_created_when_session_id_is_none(self):
        """When session_id is None, _get_or_create_session should be called
        with session_id=None, which creates a fresh session."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)

        patches, _, _ = _build_executor_patches()
        with (
            patches["set_tenant_context"],
            patches["load_definition"],
            patches["get_or_create_session"] as mock_get_session,
            patches["runtime_cls"],
            patches["emit"],
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
                session_id=None,
            )
            # _get_or_create_session was called with session_id=None
            call_args = mock_get_session.call_args
            assert call_args[0][2] is None or call_args.kwargs.get("session_id") is None

    @pytest.mark.asyncio
    async def test_existing_session_resumed_when_valid_session_id(self):
        """When a valid session_id is provided, _get_or_create_session is
        called with that session_id, enabling session resumption."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)

        existing_session_id = uuid.uuid4()
        existing_session = _make_session(id=existing_session_id)

        patches, _, _ = _build_executor_patches(session=existing_session)
        with (
            patches["set_tenant_context"],
            patches["load_definition"],
            patches["get_or_create_session"] as mock_get_session,
            patches["runtime_cls"],
            patches["emit"],
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
                session_id=existing_session_id,
            )
            # _get_or_create_session was called with the provided session_id
            call_args = mock_get_session.call_args
            assert call_args[0][2] == existing_session_id

    @pytest.mark.asyncio
    async def test_session_history_prepended_to_messages(self):
        """When a session has existing messages, they are prepended to
        the new input messages before calling the runtime."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)

        history = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]
        session_with_history = _make_session(messages=history)

        patches, _, mock_runtime_instance = _build_executor_patches(
            session=session_with_history,
        )
        with (
            patches["set_tenant_context"],
            patches["load_definition"],
            patches["get_or_create_session"],
            patches["runtime_cls"],
            patches["emit"],
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data("new question"),
                api_key="sk-test",
            )
            # runtime.run was called; check messages include history + new
            runtime_call_kwargs = mock_runtime_instance.run.call_args.kwargs
            messages = runtime_call_kwargs["messages"]
            assert len(messages) == 3  # 2 history + 1 new
            assert messages[0]["content"] == "previous question"
            assert messages[2]["content"] == "new question"


# ── 3. Error recovery (rollback then mark FAILED) ────────────────────


class TestErrorRecovery:
    @pytest.mark.asyncio
    async def test_instance_marked_failed_on_runtime_error(self):
        """When runtime.run raises an exception, the instance should be
        re-fetched after rollback and marked FAILED."""
        mock_db = make_mock_db()
        # db.get returns a mock instance after rollback
        refetched_instance = MagicMock()
        refetched_instance.id = uuid.uuid4()
        refetched_instance.steps_executed = 0
        mock_db.get = AsyncMock(return_value=refetched_instance)

        executor = AgentExecutor(mock_db)

        mock_runtime_instance = AsyncMock()
        mock_runtime_instance.run = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        mock_runtime_cls = MagicMock(return_value=mock_runtime_instance)

        definition = make_agent_definition()
        session = _make_session()

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=definition,
            ),
            patch.object(
                AgentExecutor,
                "_get_or_create_session",
                new_callable=AsyncMock,
                return_value=session,
            ),
            patch("app.agents.executor.AgentRuntime", mock_runtime_cls),
            patch("app.agents.executor.emit", new_callable=AsyncMock),
            pytest.raises(AgentExecutionError, match="LLM timeout"),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
            )

        # Instance was marked FAILED
        assert refetched_instance.status == InstanceStatus.FAILED
        assert "LLM timeout" in refetched_instance.error

    @pytest.mark.asyncio
    async def test_rollback_called_before_refetch_on_error(self):
        """db.rollback() must be called before re-fetching the instance
        so we have a clean transaction for the failure state update."""
        mock_db = make_mock_db()
        refetched_instance = MagicMock()
        refetched_instance.id = uuid.uuid4()
        refetched_instance.steps_executed = 0
        mock_db.get = AsyncMock(return_value=refetched_instance)

        # Track call order
        call_order = []
        original_rollback = mock_db.rollback
        original_get = mock_db.get

        async def tracked_rollback():
            call_order.append("rollback")
            return await original_rollback()

        async def tracked_get(*args, **kwargs):
            call_order.append("get")
            return await original_get(*args, **kwargs)

        mock_db.rollback = tracked_rollback
        mock_db.get = tracked_get

        executor = AgentExecutor(mock_db)

        mock_runtime_instance = AsyncMock()
        mock_runtime_instance.run = AsyncMock(side_effect=RuntimeError("boom"))
        mock_runtime_cls = MagicMock(return_value=mock_runtime_instance)

        definition = make_agent_definition()
        session = _make_session()

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=definition,
            ),
            patch.object(
                AgentExecutor,
                "_get_or_create_session",
                new_callable=AsyncMock,
                return_value=session,
            ),
            patch("app.agents.executor.AgentRuntime", mock_runtime_cls),
            patch("app.agents.executor.emit", new_callable=AsyncMock),
            pytest.raises(AgentExecutionError),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
            )

        assert call_order == ["rollback", "get"], f"Expected rollback before get, got: {call_order}"

    @pytest.mark.asyncio
    async def test_commit_called_after_marking_failed(self):
        """After marking the instance FAILED, db.commit() should be
        called to persist the failure state."""
        mock_db = make_mock_db()
        refetched_instance = MagicMock()
        refetched_instance.id = uuid.uuid4()
        refetched_instance.steps_executed = 0
        mock_db.get = AsyncMock(return_value=refetched_instance)

        executor = AgentExecutor(mock_db)

        mock_runtime_instance = AsyncMock()
        mock_runtime_instance.run = AsyncMock(side_effect=RuntimeError("crash"))
        mock_runtime_cls = MagicMock(return_value=mock_runtime_instance)

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=make_agent_definition(),
            ),
            patch.object(
                AgentExecutor,
                "_get_or_create_session",
                new_callable=AsyncMock,
                return_value=_make_session(),
            ),
            patch("app.agents.executor.AgentRuntime", mock_runtime_cls),
            patch("app.agents.executor.emit", new_callable=AsyncMock),
            pytest.raises(AgentExecutionError),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
            )

        # commit was called (once during error recovery)
        assert mock_db.commit.await_count >= 1


# ── 4. Session message truncation ─────────────────────────────────────


class TestSessionMessageTruncation:
    @pytest.mark.asyncio
    async def test_messages_truncated_when_exceeding_max(self):
        """When session messages exceed AGENT_SESSION_MAX_MESSAGES, only
        the most recent N messages should be kept."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)

        max_msgs = 5
        # Pre-fill session with more messages than the limit
        existing_messages = [{"role": "user", "content": f"message {i}"} for i in range(max_msgs + 10)]
        session = _make_session(messages=existing_messages)

        # Runtime returns steps that will add more messages
        steps = [
            StepResult(step_number=1, action="response", content="reply"),
        ]
        run_result = _make_run_result(steps=steps)

        patches, _, _ = _build_executor_patches(
            session=session,
            run_result=run_result,
        )

        with (
            patches["set_tenant_context"],
            patches["load_definition"],
            patches["get_or_create_session"],
            patches["runtime_cls"],
            patches["emit"],
            patch("app.config.settings.AGENT_SESSION_MAX_MESSAGES", max_msgs),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
            )

        # Session messages should have been truncated to the most recent max_msgs
        final_messages = session.messages
        assert len(final_messages) <= max_msgs

    @pytest.mark.asyncio
    async def test_messages_not_truncated_when_within_limit(self):
        """When session messages are within the limit, no truncation occurs."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)

        max_msgs = 200
        existing_messages = [{"role": "user", "content": f"msg {i}"} for i in range(3)]
        session = _make_session(messages=existing_messages)

        run_result = _make_run_result(steps=[])
        patches, _, _ = _build_executor_patches(
            session=session,
            run_result=run_result,
        )

        with (
            patches["set_tenant_context"],
            patches["load_definition"],
            patches["get_or_create_session"],
            patches["runtime_cls"],
            patches["emit"],
            patch("app.config.settings.AGENT_SESSION_MAX_MESSAGES", max_msgs),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
            )

        # All 3 original messages should remain (no truncation)
        final_messages = session.messages
        assert len(final_messages) == 3

    @pytest.mark.asyncio
    async def test_truncation_keeps_most_recent_messages(self):
        """Truncation should keep the tail (most recent) messages."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)

        max_msgs = 3
        existing_messages = [{"role": "user", "content": f"msg-{i}"} for i in range(10)]
        session = _make_session(messages=existing_messages)

        run_result = _make_run_result(steps=[])
        patches, _, _ = _build_executor_patches(
            session=session,
            run_result=run_result,
        )

        with (
            patches["set_tenant_context"],
            patches["load_definition"],
            patches["get_or_create_session"],
            patches["runtime_cls"],
            patches["emit"],
            patch("app.config.settings.AGENT_SESSION_MAX_MESSAGES", max_msgs),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data=_valid_input_data(),
                api_key="sk-test",
            )

        final_messages = session.messages
        assert len(final_messages) == max_msgs
        # The last message from the original list is "msg-9"
        assert final_messages[-1]["content"] == "msg-9"


# ── 5. Input validation ──────────────────────────────────────────────


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_empty_messages_and_no_prompt_raises(self):
        """input_data with empty messages and no 'prompt' key should raise."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)
        definition = make_agent_definition()

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=definition,
            ),
            pytest.raises(AgentExecutionError, match=r"messages.*prompt"),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data={"messages": []},
                api_key="sk-test",
            )

    @pytest.mark.asyncio
    async def test_no_messages_key_and_no_prompt_raises(self):
        """input_data with neither 'messages' nor 'prompt' should raise."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)
        definition = make_agent_definition()

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=definition,
            ),
            pytest.raises(AgentExecutionError, match=r"messages.*prompt"),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data={},
                api_key="sk-test",
            )

    @pytest.mark.asyncio
    async def test_invalid_message_structure_missing_role(self):
        """Messages missing the 'role' key should raise."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)
        definition = make_agent_definition()

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=definition,
            ),
            pytest.raises(AgentExecutionError, match=r"role.*content"),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data={"messages": [{"content": "hello"}]},
                api_key="sk-test",
            )

    @pytest.mark.asyncio
    async def test_invalid_message_structure_missing_content(self):
        """Messages missing the 'content' key should raise."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)
        definition = make_agent_definition()

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=definition,
            ),
            pytest.raises(AgentExecutionError, match=r"role.*content"),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data={"messages": [{"role": "user"}]},
                api_key="sk-test",
            )

    @pytest.mark.asyncio
    async def test_invalid_message_structure_not_a_dict(self):
        """Messages that are not dicts should raise."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)
        definition = make_agent_definition()

        with (
            patch("app.agents.executor.set_tenant_context", new_callable=AsyncMock),
            patch.object(
                AgentExecutor,
                "_load_definition",
                new_callable=AsyncMock,
                return_value=definition,
            ),
            pytest.raises(AgentExecutionError, match=r"role.*content"),
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data={"messages": ["not a dict"]},
                api_key="sk-test",
            )

    @pytest.mark.asyncio
    async def test_prompt_fallback_creates_valid_message(self):
        """When 'messages' is empty but 'prompt' is provided, it should
        be converted to a valid user message and the run should proceed."""
        mock_db = make_mock_db()
        executor = AgentExecutor(mock_db)

        patches, _, mock_runtime_instance = _build_executor_patches()
        with (
            patches["set_tenant_context"],
            patches["load_definition"],
            patches["get_or_create_session"],
            patches["runtime_cls"],
            patches["emit"],
        ):
            await executor.run(
                definition_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                input_data={"prompt": "Tell me something"},
                api_key="sk-test",
            )

        # runtime.run was called with the prompt converted to a message
        runtime_call_kwargs = mock_runtime_instance.run.call_args.kwargs
        messages = runtime_call_kwargs["messages"]
        assert any(m["content"] == "Tell me something" for m in messages)
        assert any(m["role"] == "user" for m in messages)
