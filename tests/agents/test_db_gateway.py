"""Tests for AgentDatabaseGateway — query validation, table extraction, allowlists, rate limiting, and SQL injection."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.db_gateway import AgentDatabaseGateway, GatewayViolationError, QueryPolicy


# ── Helpers ────────────────────────────────────────────────────────────

_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _make_gateway(policy: QueryPolicy | None = None) -> AgentDatabaseGateway:
    return AgentDatabaseGateway(
        tenant_id=_TENANT,
        agent_id="test-agent",
        instance_id="test-instance",
        policy=policy or QueryPolicy(require_where_clause=False),
    )


# ── TestQueryValidation ───────────────────────────────────────────────


class TestQueryValidation:
    """Validate _validate_query against allowed operations, forbidden patterns, and complexity limits."""

    def test_select_query_passes(self):
        gw = _make_gateway()
        # Should not raise
        gw._validate_query("SELECT id FROM users WHERE id = 1")

    def test_insert_blocked_by_default(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("INSERT INTO users (name) VALUES ('x')")
        assert exc_info.value.violation_type == "disallowed_operation"

    def test_delete_blocked_by_default(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("DELETE FROM users WHERE id = 1")
        assert exc_info.value.violation_type == "disallowed_operation"

    def test_forbidden_drop_blocked(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("DROP TABLE users")
        assert exc_info.value.violation_type == "forbidden_pattern"

    def test_forbidden_truncate_blocked(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("TRUNCATE users")
        assert exc_info.value.violation_type == "forbidden_pattern"

    def test_forbidden_pg_catalog_blocked(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("SELECT * FROM pg_catalog.pg_tables")
        assert exc_info.value.violation_type == "forbidden_pattern"

    def test_forbidden_pg_sleep_blocked(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("SELECT pg_sleep(10)")
        assert exc_info.value.violation_type == "forbidden_pattern"

    def test_forbidden_information_schema_blocked(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("SELECT * FROM information_schema.tables WHERE 1=1")
        assert exc_info.value.violation_type == "forbidden_pattern"

    def test_forbidden_set_role_blocked(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("SET ROLE admin")
        assert exc_info.value.violation_type == "forbidden_pattern"

    def test_custom_operations_allowed(self):
        policy = QueryPolicy(
            allowed_operations=["SELECT", "INSERT"],
            require_where_clause=False,
        )
        gw = _make_gateway(policy)
        # INSERT should pass when explicitly allowed
        gw._validate_query("INSERT INTO users (name) VALUES ('x')")

    def test_missing_where_clause_blocked(self):
        policy = QueryPolicy(require_where_clause=True)
        gw = _make_gateway(policy)
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("SELECT * FROM users")
        assert exc_info.value.violation_type == "missing_where_clause"

    def test_where_clause_present_passes(self):
        policy = QueryPolicy(require_where_clause=True)
        gw = _make_gateway(policy)
        gw._validate_query("SELECT * FROM users WHERE id = 1")

    def test_limit_clause_instead_of_where_passes(self):
        policy = QueryPolicy(require_where_clause=True)
        gw = _make_gateway(policy)
        gw._validate_query("SELECT * FROM users LIMIT 10")

    def test_excessive_joins_blocked(self):
        policy = QueryPolicy(max_joins=3, require_where_clause=False)
        gw = _make_gateway(policy)
        query = (
            "SELECT a.id FROM a "
            "JOIN b ON a.id=b.aid "
            "JOIN c ON b.id=c.bid "
            "JOIN d ON c.id=d.cid "
            "JOIN e ON d.id=e.did "
            "WHERE 1=1"
        )
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query(query)
        assert exc_info.value.violation_type == "excessive_joins"

    def test_excessive_subqueries_blocked(self):
        policy = QueryPolicy(max_subqueries=2, require_where_clause=False)
        gw = _make_gateway(policy)
        query = (
            "SELECT * FROM users WHERE id IN (SELECT id FROM a) "
            "AND name IN (SELECT name FROM b) "
            "AND email IN (SELECT email FROM c)"
        )
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query(query)
        assert exc_info.value.violation_type == "excessive_subqueries"

    def test_query_too_long_blocked(self):
        gw = _make_gateway()
        query = "SELECT " + "x" * 20_000
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query(query)
        assert exc_info.value.violation_type == "query_too_long"


# ── TestTableNameExtraction ───────────────────────────────────────────


class TestTableNameExtraction:
    """Validate _extract_table_names correctly parses table references."""

    def _extract(self, query: str) -> set[str]:
        gw = _make_gateway()
        return gw._extract_table_names(query)

    def test_simple_from(self):
        assert self._extract("SELECT x FROM users WHERE 1=1") == {"users"}

    def test_join_clause(self):
        tables = self._extract(
            "SELECT x FROM users JOIN orders ON u.id=o.uid WHERE 1=1"
        )
        assert tables == {"users", "orders"}

    def test_quoted_table(self):
        tables = self._extract('SELECT x FROM "SecretTable" WHERE 1=1')
        assert "secrettable" in tables

    def test_schema_qualified(self):
        tables = self._extract("SELECT x FROM public.users WHERE 1=1")
        assert "users" in tables
        assert "public.users" in tables

    def test_schema_qualified_quoted(self):
        tables = self._extract('SELECT x FROM public."Users" WHERE 1=1')
        assert "users" in tables
        assert "public.users" in tables


# ── TestTableAllowlist ────────────────────────────────────────────────


class TestTableAllowlist:
    """Validate allowed_tables enforcement in _validate_query."""

    def test_allowed_table_passes(self):
        policy = QueryPolicy(
            allowed_tables=["users"],
            require_where_clause=False,
        )
        gw = _make_gateway(policy)
        gw._validate_query("SELECT * FROM users WHERE 1=1")

    def test_disallowed_table_blocked(self):
        policy = QueryPolicy(
            allowed_tables=["users"],
            require_where_clause=False,
        )
        gw = _make_gateway(policy)
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("SELECT * FROM secrets WHERE 1=1")
        assert exc_info.value.violation_type == "disallowed_table"

    def test_quoted_table_checked(self):
        policy = QueryPolicy(
            allowed_tables=["users"],
            require_where_clause=False,
        )
        gw = _make_gateway(policy)
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query('SELECT * FROM "secrets" WHERE 1=1')
        assert exc_info.value.violation_type == "disallowed_table"


# ── TestRateLimiting ──────────────────────────────────────────────────


class TestRateLimiting:
    """Validate rate limiting through Redis Lua scripts."""

    @pytest.mark.asyncio
    async def test_within_rate_limit(self, mock_redis_pool):
        mock_redis_pool.eval = AsyncMock(return_value=1)
        gw = _make_gateway()
        # Should not raise
        await gw._check_rate_limit()

    @pytest.mark.asyncio
    async def test_exceeds_rate_limit(self, mock_redis_pool):
        mock_redis_pool.eval = AsyncMock(return_value=-1)
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            await gw._check_rate_limit()
        assert exc_info.value.violation_type == "rate_limit_exceeded"

    @pytest.mark.asyncio
    async def test_redis_unavailable_fails_closed(self, mock_redis_pool):
        mock_redis_pool.eval = AsyncMock(side_effect=ConnectionError("Redis down"))
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            await gw._check_rate_limit()
        assert exc_info.value.violation_type == "rate_limit_unavailable"


# ── TestSQLInjectionAttacks ───────────────────────────────────────────


class TestSQLInjectionAttacks:
    """Simulate real-world SQL injection vectors against the gateway."""

    def test_union_select_attack(self):
        policy = QueryPolicy(
            allowed_tables=["users"],
            require_where_clause=False,
        )
        gw = _make_gateway(policy)
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query(
                "SELECT name FROM users WHERE id=1 UNION SELECT password FROM admins"
            )
        assert exc_info.value.violation_type == "disallowed_table"

    def test_semicolon_stacked_query(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("SELECT 1; DROP TABLE users")
        # sqlparse multi-statement check runs before forbidden patterns
        assert exc_info.value.violation_type == "multi_statement"

    def test_pg_sleep_injection(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("SELECT * FROM users WHERE name = '' OR pg_sleep(10)--")
        assert exc_info.value.violation_type == "forbidden_pattern"

    def test_information_schema_probe(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query(
                "SELECT table_name FROM information_schema.columns WHERE 1=1"
            )
        assert exc_info.value.violation_type == "forbidden_pattern"


# ── TestQueryPolicyFromDict ──────────────────────────────────────────


class TestQueryPolicyFromDict:
    """Validate QueryPolicy.from_dict coercion, clamping, and SQL injection safety."""

    def test_sql_injection_in_statement_timeout(self):
        """SQL injection string in statement_timeout_ms is coerced to safe int or fallback."""
        policy = QueryPolicy.from_dict({"statement_timeout_ms": "1'; DROP TABLE x; --"})
        # The string is not a valid int, so it falls back to 0
        assert isinstance(policy.statement_timeout_ms, int)
        assert policy.statement_timeout_ms == 0

    def test_non_int_string_coerced(self):
        """Numeric string is coerced to int."""
        policy = QueryPolicy.from_dict({"statement_timeout_ms": "5000"})
        assert policy.statement_timeout_ms == 5000

    def test_non_int_float_coerced(self):
        """Float value is coerced to int (truncated)."""
        policy = QueryPolicy.from_dict({"statement_timeout_ms": 5000.7})
        assert isinstance(policy.statement_timeout_ms, int)
        assert policy.statement_timeout_ms == 5000

    def test_non_int_none_coerced(self):
        """None value is coerced to fallback 0."""
        policy = QueryPolicy.from_dict({"statement_timeout_ms": None})
        assert policy.statement_timeout_ms == 0

    def test_statement_timeout_clamped_lower(self):
        """Values below 100ms are clamped to 100."""
        policy = QueryPolicy.from_dict({"statement_timeout_ms": 10})
        assert policy.statement_timeout_ms == 100

    def test_statement_timeout_clamped_upper(self):
        """Values above 300000ms are clamped to 300000."""
        policy = QueryPolicy.from_dict({"statement_timeout_ms": 999_999})
        assert policy.statement_timeout_ms == 300_000

    def test_statement_timeout_zero_not_clamped(self):
        """Zero means 'use global default' and should not be clamped."""
        policy = QueryPolicy.from_dict({"statement_timeout_ms": 0})
        assert policy.statement_timeout_ms == 0

    def test_statement_timeout_within_range(self):
        """Valid values within range are preserved."""
        policy = QueryPolicy.from_dict({"statement_timeout_ms": 5000})
        assert policy.statement_timeout_ms == 5000


# ── TestMultiStatementBlocking ───────────────────────────────────────


class TestMultiStatementBlocking:
    """Validate AST-based multi-statement query detection via sqlparse."""

    def test_multi_statement_blocked(self):
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            gw._validate_query("SELECT 1; DROP TABLE users")
        assert exc_info.value.violation_type == "multi_statement"


# ── TestAdvancedTableExtraction ──────────────────────────────────────


class TestAdvancedTableExtraction:
    """Validate AST-based table extraction for CTEs, subqueries, and UNIONs."""

    def _extract(self, query: str) -> set[str]:
        gw = _make_gateway()
        return gw._extract_table_names(query)

    def test_cte_table_extraction(self):
        """CTE (WITH clause) should extract the referenced source table."""
        tables = self._extract(
            "WITH cte AS (SELECT * FROM secret_table) SELECT * FROM cte"
        )
        assert "secret_table" in tables

    def test_subquery_in_where_table_extraction(self):
        """Subquery in WHERE clause should extract both outer and inner tables."""
        tables = self._extract(
            "SELECT * FROM public_table WHERE id IN (SELECT id FROM secret_table)"
        )
        assert "public_table" in tables
        assert "secret_table" in tables

    def test_union_table_extraction(self):
        """UNION queries should extract tables from both sides."""
        tables = self._extract(
            "SELECT name FROM users WHERE id = 1 UNION SELECT password FROM admins"
        )
        assert "users" in tables
        assert "admins" in tables


# ── TestByteTrackingFailClosed ───────────────────────────────────────


class TestByteTrackingFailClosed:
    """Validate that byte tracking Redis failure raises GatewayViolationError (fail-closed)."""

    @pytest.mark.asyncio
    async def test_redis_failure_raises_violation(self, mock_redis_pool):
        """Redis failure in _track_bytes raises GatewayViolationError."""
        mock_redis_pool.eval = AsyncMock(side_effect=Exception("Redis connection refused"))
        gw = _make_gateway()
        with pytest.raises(GatewayViolationError) as exc_info:
            await gw._track_bytes(1024)
        assert exc_info.value.violation_type == "byte_tracking_unavailable"
