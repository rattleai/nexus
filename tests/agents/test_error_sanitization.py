"""Tests for error message sanitization in the database gateway.

Verifies that:
    - db_gateway.execute_query sanitizes sensitive internal error details
    - Client-facing error says "Query execution failed" (no hostnames, ports, etc.)
    - Server-side logger still receives the full original error for debugging
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.db_gateway import AgentDatabaseGateway, GatewayViolationError, QueryPolicy


# ── Helpers ────────────────────────────────────────────────────────────


def _make_gateway(tenant_id: uuid.UUID | None = None) -> AgentDatabaseGateway:
    return AgentDatabaseGateway(
        tenant_id=tenant_id or uuid.uuid4(),
        agent_id="test-agent",
        instance_id="test-instance",
        policy=QueryPolicy(require_where_clause=False),
    )


def _make_db_that_raises(error: Exception) -> AsyncMock:
    """Create a mock db where execute raises the given error on the query call.

    The first two calls succeed (SET LOCAL timeout, SELECT tenant_id check),
    and the third call (the actual query) raises.
    """
    db = AsyncMock()

    # Call 1: _set_statement_timeout -> SET LOCAL
    # Call 2: _verify_tenant_context -> SELECT current_setting
    # Call 3: actual query -> raises
    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = None  # Will be replaced per-test
    success_result = MagicMock()

    call_count = 0

    async def mock_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # SET LOCAL statement_timeout
            return success_result
        elif call_count == 2:
            # SELECT current_setting (tenant context check)
            return tenant_result
        else:
            # Actual query
            raise error

    db.execute = AsyncMock(side_effect=mock_execute)
    return db, tenant_result


# ── TestErrorSanitization ─────────────────────────────────────────────


class TestErrorSanitization:
    """execute_query must never leak internal infra details to the caller."""

    @pytest.mark.asyncio
    async def test_connection_refused_sanitized(self, mock_redis_pool):
        """RuntimeError with internal hostname/port must not appear in result.error."""
        gw = _make_gateway()
        sensitive_error = RuntimeError(
            "Connection to secret-db.internal:5432 refused"
        )
        db, tenant_result = _make_db_that_raises(sensitive_error)
        tenant_result.scalar_one_or_none.return_value = str(gw.tenant_id)

        result = await gw.execute_query(db, "SELECT id FROM products WHERE id = 1")

        assert result.success is False
        assert result.error == "Query execution failed"
        # Must NOT contain any internal infrastructure details
        assert "secret-db" not in result.error
        assert "5432" not in result.error
        assert "internal" not in result.error
        assert "Connection" not in result.error

    @pytest.mark.asyncio
    async def test_authentication_error_sanitized(self, mock_redis_pool):
        """Auth errors with credentials must not leak to client."""
        gw = _make_gateway()
        sensitive_error = Exception(
            'FATAL: password authentication failed for user "admin_readonly" '
            'on host "db-primary-rw.vpc.internal"'
        )
        db, tenant_result = _make_db_that_raises(sensitive_error)
        tenant_result.scalar_one_or_none.return_value = str(gw.tenant_id)

        result = await gw.execute_query(db, "SELECT id FROM products WHERE id = 1")

        assert result.success is False
        assert result.error == "Query execution failed"
        assert "admin_readonly" not in result.error
        assert "db-primary" not in result.error
        assert "password" not in result.error

    @pytest.mark.asyncio
    async def test_sql_syntax_error_sanitized(self, mock_redis_pool):
        """SQL syntax errors must not reveal table structure."""
        gw = _make_gateway()
        sensitive_error = Exception(
            'ERROR: column "secret_column" of relation "internal_payments" does not exist '
            'LINE 1: SELECT secret_column FROM internal_payments ^'
        )
        db, tenant_result = _make_db_that_raises(sensitive_error)
        tenant_result.scalar_one_or_none.return_value = str(gw.tenant_id)

        result = await gw.execute_query(db, "SELECT id FROM products WHERE id = 1")

        assert result.success is False
        assert result.error == "Query execution failed"
        assert "secret_column" not in result.error
        assert "internal_payments" not in result.error

    @pytest.mark.asyncio
    async def test_timeout_error_sanitized(self, mock_redis_pool):
        """Timeout errors must not reveal server-side config."""
        gw = _make_gateway()
        sensitive_error = Exception(
            "canceling statement due to statement timeout; "
            "server=10.0.5.42, port=5432, pid=12345"
        )
        db, tenant_result = _make_db_that_raises(sensitive_error)
        tenant_result.scalar_one_or_none.return_value = str(gw.tenant_id)

        result = await gw.execute_query(db, "SELECT id FROM products WHERE id = 1")

        assert result.success is False
        assert result.error == "Query execution failed"
        assert "10.0.5.42" not in result.error
        assert "pid=" not in result.error


# ── TestErrorStillLoggedServerSide ────────────────────────────────────


class TestErrorStillLoggedServerSide:
    """Full error details must still be logged server-side for debugging."""

    @pytest.mark.asyncio
    async def test_full_error_logged(self, mock_redis_pool):
        """Logger receives the original error string, not the sanitized one."""
        gw = _make_gateway()
        original_msg = "Connection to secret-db.internal:5432 refused"
        sensitive_error = RuntimeError(original_msg)
        db, tenant_result = _make_db_that_raises(sensitive_error)
        tenant_result.scalar_one_or_none.return_value = str(gw.tenant_id)

        with patch("app.agents.db_gateway.logger") as mock_logger:
            result = await gw.execute_query(db, "SELECT id FROM products WHERE id = 1")

        assert result.success is False
        assert result.error == "Query execution failed"

        # The logger.warning call should contain the full error for server-side debugging
        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        # The error kwarg should contain the original sensitive message (truncated at 500)
        logged_error = call_kwargs.kwargs.get("error", "") or call_kwargs[1].get("error", "")
        assert "secret-db" in logged_error or original_msg[:500] in logged_error

    @pytest.mark.asyncio
    async def test_gateway_violation_not_sanitized(self, mock_redis_pool):
        """GatewayViolationError is re-raised directly, not caught by the sanitizer."""
        gw = _make_gateway()

        # This error should go through _validate_query, not execute_query's generic handler
        with pytest.raises(GatewayViolationError) as exc_info:
            await gw.execute_query(
                AsyncMock(),  # db mock
                "DROP TABLE users",
            )

        assert exc_info.value.violation_type == "forbidden_pattern"
