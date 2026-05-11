"""Agent Database Gateway — mediates ALL agent database interactions.

Provides:
    - Query allowlisting: permitted patterns per agent (SELECT-only by default)
    - Row limit enforcement: hard cap on result rows returned to agents
    - Query complexity analysis: reject excessive JOINs, subqueries, missing WHERE
    - Statement timeout per-agent: SET LOCAL before each query
    - Connection isolation: agents get read-only sessions by default
    - Query logging: every query logged with tenant_id, agent_id, query hash, metrics
    - Rate limiting: per-agent query rate via Redis Lua (reuses governance pattern)

Integrates with:
    - app/db/session.py for RLS context and session management
    - app/agents/governance.py for policy checks and Redis Lua patterns
    - app/agents/events.py for security event emission
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import sqlparse
import structlog

from app.config import settings
from app.core.redis import redis_pool

logger = structlog.stdlib.get_logger()

# Redis key for per-agent query rate limiting
_AGENT_QUERY_RATE_KEY = "agent:db:rate:{tenant_id}:{agent_id}"
_AGENT_QUERY_BYTES_KEY = "agent:db:bytes:{tenant_id}:{instance_id}"

# Lua script: atomic check-and-increment for query rate limiting.
# Uses Redis server-side Lua (not Python eval).
_RATE_CHECK_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
if current >= limit then
    return -1
end
redis.call('INCR', KEYS[1])
if ttl > 0 then
    redis.call('EXPIRE', KEYS[1], ttl)
end
return current + 1
"""

# Lua script: atomic check-and-add for byte tracking.
# Uses Redis server-side Lua (not Python eval).
_BYTES_CHECK_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local add_bytes = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
if current + add_bytes > limit then
    return -1
end
local new_total = current + add_bytes
redis.call('SET', KEYS[1], new_total)
if ttl > 0 then
    redis.call('EXPIRE', KEYS[1], ttl)
end
return new_total
"""

# SQL patterns that are NEVER allowed for agents
_FORBIDDEN_SQL_PATTERNS = [
    re.compile(r"\bDROP\s+", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\s+", re.IGNORECASE),
    re.compile(r"\bALTER\s+", re.IGNORECASE),
    re.compile(r"\bCREATE\s+", re.IGNORECASE),
    re.compile(r"\bGRANT\s+", re.IGNORECASE),
    re.compile(r"\bREVOKE\s+", re.IGNORECASE),
    re.compile(r"\bCOPY\s+", re.IGNORECASE),
    re.compile(r"\bEXECUTE\s+", re.IGNORECASE),
    re.compile(r"\bPREPARE\s+", re.IGNORECASE),
    re.compile(r"\bSET\s+ROLE", re.IGNORECASE),
    re.compile(r"\bSET\s+SESSION", re.IGNORECASE),
    re.compile(r"\bLOAD\s+", re.IGNORECASE),
    re.compile(r"pg_catalog\.", re.IGNORECASE),
    re.compile(r"information_schema\.", re.IGNORECASE),
    re.compile(r"\bpg_sleep\b", re.IGNORECASE),
]

# Regex for counting JOINs and subqueries
_JOIN_RE = re.compile(r"\bJOIN\b", re.IGNORECASE)
_SUBQUERY_RE = re.compile(r"\(\s*SELECT\b", re.IGNORECASE)
_WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)


@dataclass
class QueryPolicy:
    """Per-agent database query policy."""

    allowed_operations: list[str] = field(default_factory=lambda: ["SELECT"])
    allowed_tables: list[str] = field(default_factory=list)  # empty = all tenant-scoped
    max_result_rows: int = 0  # 0 = use global default
    max_joins: int = 0  # 0 = use global default
    max_subqueries: int = 2
    statement_timeout_ms: int = 0  # 0 = use global default
    max_queries_per_minute: int = 0  # 0 = use global default
    max_result_bytes_per_query: int = 0  # 0 = use global default
    max_total_db_bytes_per_run: int = 0  # 0 = use global default
    require_where_clause: bool = True

    def __post_init__(self):
        """Coerce and validate types from untrusted JSON input."""
        int_fields = [
            "max_result_rows",
            "max_joins",
            "max_subqueries",
            "statement_timeout_ms",
            "max_queries_per_minute",
            "max_result_bytes_per_query",
            "max_total_db_bytes_per_run",
        ]
        for field_name in int_fields:
            val = getattr(self, field_name)
            if not isinstance(val, int):
                try:
                    setattr(self, field_name, int(val))
                except (ValueError, TypeError):
                    setattr(self, field_name, 0)

        # Clamp statement_timeout_ms to sane range
        if self.statement_timeout_ms != 0:
            self.statement_timeout_ms = max(100, min(self.statement_timeout_ms, 300_000))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueryPolicy:
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


@dataclass
class QueryResult:
    """Result from a gateway-mediated query."""

    success: bool
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    duration_ms: int = 0
    error: str = ""
    query_hash: str = ""


class GatewayViolationError(Exception):
    """Raised when a query violates the gateway policy."""

    def __init__(self, violation_type: str, message: str):
        self.violation_type = violation_type
        super().__init__(message)


class AgentDatabaseGateway:
    """Mediates ALL agent database interactions with policy enforcement.

    Usage:
        gateway = AgentDatabaseGateway(
            tenant_id=..., agent_id=..., instance_id=...,
            policy=QueryPolicy.from_dict(definition.db_access_policy),
        )
        result = await gateway.execute_query(db, "SELECT name FROM products WHERE ...")
    """

    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        agent_id: str,
        instance_id: str,
        policy: QueryPolicy | None = None,
    ):
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.instance_id = instance_id
        self.policy = policy or QueryPolicy()

    async def execute_query(
        self,
        db: Any,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a query through the gateway with full policy enforcement."""
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        start = time.monotonic()

        try:
            # 1. Validate query against policy
            self._validate_query(query)

            # 2. Check rate limit
            await self._check_rate_limit()

            # 3. Set agent-specific statement timeout
            await self._set_statement_timeout(db)

            # 3b. Verify RLS tenant context is set correctly (fail-closed)
            await self._verify_tenant_context(db)

            # 4. Execute the query
            from sqlalchemy import text

            result = await db.execute(text(query), params or {})

            # 5. Fetch rows with limit enforcement
            max_rows = self.policy.max_result_rows or settings.AGENT_DB_MAX_RESULT_ROWS
            rows_raw = result.mappings().fetchmany(max_rows + 1)
            truncated = len(rows_raw) > max_rows
            rows = [dict(r) for r in rows_raw[:max_rows]]

            # 6. Check result byte size
            import json

            result_bytes = len(json.dumps(rows, default=str).encode())
            max_bytes = self.policy.max_result_bytes_per_query or settings.AGENT_DB_MAX_RESULT_BYTES
            if result_bytes > max_bytes:
                await self._emit_block_event("result_size_exceeded", query_hash)
                raise GatewayViolationError(
                    "result_size_exceeded",
                    f"Query result ({result_bytes} bytes) exceeds limit ({max_bytes} bytes)",
                )

            # 7. Track cumulative bytes for this run
            await self._track_bytes(result_bytes)

            duration_ms = int((time.monotonic() - start) * 1000)

            # 8. Audit log
            logger.info(
                "agent_db_query",
                tenant_id=str(self.tenant_id),
                agent_id=self.agent_id,
                instance_id=self.instance_id,
                query_hash=query_hash,
                row_count=len(rows),
                result_bytes=result_bytes,
                duration_ms=duration_ms,
                truncated=truncated,
            )

            return QueryResult(
                success=True,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                duration_ms=duration_ms,
                query_hash=query_hash,
            )

        except GatewayViolationError:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "agent_db_query_failed",
                tenant_id=str(self.tenant_id),
                agent_id=self.agent_id,
                query_hash=query_hash,
                error=str(exc)[:500],
                duration_ms=duration_ms,
            )
            return QueryResult(
                success=False,
                error="Query execution failed",
                duration_ms=duration_ms,
                query_hash=query_hash,
            )

    # Maximum query length to prevent regex DoS and memory exhaustion
    _MAX_QUERY_LENGTH = 10_000

    def _validate_query(self, query: str) -> None:
        """Validate a query against the gateway policy."""
        normalized = query.strip()

        # Check query length before any regex processing
        if len(normalized) > self._MAX_QUERY_LENGTH:
            raise GatewayViolationError(
                "query_too_long",
                f"Query length ({len(normalized)}) exceeds maximum ({self._MAX_QUERY_LENGTH})",
            )

        # Check for multi-statement queries (prevents piggyback attacks)
        statements = sqlparse.parse(normalized)
        if len(statements) > 1:
            raise GatewayViolationError(
                "multi_statement",
                "Multi-statement queries are not allowed",
            )

        # Check forbidden patterns
        for pattern in _FORBIDDEN_SQL_PATTERNS:
            if pattern.search(normalized):
                raise GatewayViolationError(
                    "forbidden_pattern",
                    "Query contains forbidden SQL pattern",
                )

        # Check allowed operations
        first_word = normalized.split()[0].upper() if normalized.split() else ""
        allowed_ops = [op.upper() for op in self.policy.allowed_operations]
        if first_word not in allowed_ops:
            raise GatewayViolationError(
                "disallowed_operation",
                f"Operation '{first_word}' is not allowed (allowed: {allowed_ops})",
            )

        # Check allowed tables (if specified)
        if self.policy.allowed_tables:
            tables_in_query = self._extract_table_names(normalized)
            disallowed = tables_in_query - set(self.policy.allowed_tables)
            if disallowed:
                raise GatewayViolationError(
                    "disallowed_table",
                    f"Query references disallowed tables: {disallowed}",
                )

        # Check JOIN complexity
        max_joins = self.policy.max_joins or settings.AGENT_DB_MAX_JOINS
        join_count = len(_JOIN_RE.findall(normalized))
        if join_count > max_joins:
            raise GatewayViolationError(
                "excessive_joins",
                f"Query has {join_count} JOINs (max {max_joins})",
            )

        # Check subquery complexity
        subquery_count = len(_SUBQUERY_RE.findall(normalized))
        if subquery_count > self.policy.max_subqueries:
            raise GatewayViolationError(
                "excessive_subqueries",
                f"Query has {subquery_count} subqueries (max {self.policy.max_subqueries})",
            )

        # Check WHERE clause requirement for SELECT on large tables
        if (
            first_word == "SELECT"
            and self.policy.require_where_clause
            and not _WHERE_RE.search(normalized)
            and "LIMIT" not in normalized.upper()
        ):
            raise GatewayViolationError(
                "missing_where_clause",
                "SELECT queries must include a WHERE clause or LIMIT",
            )

    def _extract_table_names(self, query: str) -> set[str]:
        """Extract ALL table names from a SQL query using AST parsing.

        Uses sqlparse for robust extraction that handles CTEs, subqueries,
        UNION, INSERT..SELECT, and other constructs that regex misses.
        """
        tables: set[str] = set()
        parsed = sqlparse.parse(query)
        for statement in parsed:
            self._extract_tables_from_tokens(statement.tokens, tables)
        return tables

    def _extract_tables_from_tokens(self, tokens, tables: set[str]) -> None:
        """Recursively extract table names from parsed SQL tokens."""
        from sqlparse import tokens as T
        from sqlparse.sql import Identifier, IdentifierList, Parenthesis, Where

        expect_table = False
        for token in tokens:
            if token.ttype is T.Keyword and token.normalized in (
                "FROM",
                "JOIN",
                "INNER JOIN",
                "LEFT JOIN",
                "RIGHT JOIN",
                "FULL JOIN",
                "CROSS JOIN",
                "LEFT OUTER JOIN",
                "RIGHT OUTER JOIN",
                "FULL OUTER JOIN",
                "INTO",
                "UPDATE",
                "TABLE",
            ):
                expect_table = True
                continue

            if expect_table:
                if isinstance(token, Identifier):
                    name = token.get_real_name()
                    if name:
                        tables.add(name.lower())
                        schema = token.get_parent_name()
                        if schema:
                            tables.add(f"{schema.lower()}.{name.lower()}")
                    expect_table = False
                elif isinstance(token, IdentifierList):
                    for identifier in token.get_identifiers():
                        if isinstance(identifier, Identifier):
                            name = identifier.get_real_name()
                            if name:
                                tables.add(name.lower())
                                schema = identifier.get_parent_name()
                                if schema:
                                    tables.add(f"{schema.lower()}.{name.lower()}")
                    expect_table = False
                elif token.ttype is not T.Whitespace:
                    expect_table = False

            # Recurse into subqueries, CTEs, WHERE clauses, etc.
            if isinstance(token, (Parenthesis, Where)):
                self._extract_tables_from_tokens(token.tokens, tables)
            elif isinstance(token, Identifier):
                # CTE definitions (e.g. "cte AS (SELECT ...)") contain a
                # Parenthesis child with the subquery — recurse into it.
                for child in token.tokens:
                    if isinstance(child, Parenthesis):
                        self._extract_tables_from_tokens(child.tokens, tables)
            elif hasattr(token, "tokens"):
                self._extract_tables_from_tokens(token.tokens, tables)

    async def _check_rate_limit(self) -> None:
        """Check per-agent query rate limit via Redis Lua."""
        max_qpm = self.policy.max_queries_per_minute or settings.AGENT_DB_MAX_QUERIES_PER_MINUTE
        rate_key = _AGENT_QUERY_RATE_KEY.format(
            tenant_id=self.tenant_id,
            agent_id=self.agent_id,
        )
        try:
            # redis_pool.eval runs a Lua script on the Redis server (not Python eval)
            result = await redis_pool.eval(
                _RATE_CHECK_LUA,
                1,
                rate_key,
                str(max_qpm),
                "60",
            )
            if int(result) == -1:
                raise GatewayViolationError(
                    "rate_limit_exceeded",
                    f"Agent exceeded query rate limit ({max_qpm}/min)",
                )
        except GatewayViolationError:
            raise
        except Exception:
            # Fail-closed: block if Redis unavailable
            logger.error("agent_db_gateway_redis_unavailable", exc_info=True)
            raise GatewayViolationError(
                "rate_limit_unavailable",
                "Unable to verify query rate limit (Redis unavailable)",
            )

    async def _set_statement_timeout(self, db: Any) -> None:
        """Set per-agent statement timeout (tighter than global 30s)."""
        timeout_ms = self.policy.statement_timeout_ms or settings.AGENT_DB_STATEMENT_TIMEOUT_MS
        # Strict validation: must be positive int within sane range to prevent SQL injection
        if not isinstance(timeout_ms, int) or timeout_ms < 100 or timeout_ms > 300_000:
            timeout_ms = settings.AGENT_DB_STATEMENT_TIMEOUT_MS
        from sqlalchemy import text

        await db.execute(
            text("SET LOCAL statement_timeout = :timeout"),
            {"timeout": str(timeout_ms)},
        )

    async def _verify_tenant_context(self, db: Any) -> None:
        """Verify that the database session has the correct RLS tenant context.

        Fail-closed: if the tenant context is missing or mismatched, block the query.
        This is a defense-in-depth check — RLS should already be set by the caller,
        but this prevents data leaks if the caller forgot or used the wrong session.
        """
        from sqlalchemy import text

        try:
            result = await db.execute(text("SELECT current_setting('app.tenant_id', true)"))
            row = result.scalar_one_or_none()
            if not row:
                raise GatewayViolationError(
                    "tenant_context_missing",
                    "Database session has no tenant context (app.tenant_id not set)",
                )
            if row != str(self.tenant_id):
                logger.error(
                    "agent_db_tenant_context_mismatch",
                    expected=str(self.tenant_id),
                    actual=row[:36],  # truncate to UUID length for safety
                )
                raise GatewayViolationError(
                    "tenant_context_mismatch",
                    "Database session tenant context does not match agent tenant",
                )
        except GatewayViolationError:
            raise
        except Exception:
            # Fail-closed: if we can't verify tenant context, block the query
            logger.error("agent_db_tenant_context_check_failed", exc_info=True)
            raise GatewayViolationError(
                "tenant_context_unavailable",
                "Unable to verify tenant context",
            )

    async def _track_bytes(self, result_bytes: int) -> None:
        """Track cumulative bytes returned to agent for this run."""
        max_total = self.policy.max_total_db_bytes_per_run or (settings.AGENT_DB_MAX_RESULT_BYTES * 10)
        bytes_key = _AGENT_QUERY_BYTES_KEY.format(
            tenant_id=self.tenant_id,
            instance_id=self.instance_id,
        )
        try:
            # redis_pool.eval runs a Lua script on the Redis server (not Python eval)
            result = await redis_pool.eval(
                _BYTES_CHECK_LUA,
                1,
                bytes_key,
                str(result_bytes),
                str(max_total),
                "3600",
            )
            if int(result) == -1:
                raise GatewayViolationError(
                    "total_bytes_exceeded",
                    f"Agent exceeded total DB bytes limit ({max_total} bytes)",
                )
        except GatewayViolationError:
            raise
        except Exception:
            # Fail-closed: block if we can't verify byte limits
            logger.error("agent_db_bytes_tracking_failed", exc_info=True)
            raise GatewayViolationError(
                "byte_tracking_unavailable",
                "Unable to track query bytes (Redis unavailable)",
            )

    async def _emit_block_event(self, reason: str, query_hash: str) -> None:
        """Emit a security event when a query is blocked."""
        from app.agents.events import AgentDBQueryBlocked
        from app.core.events import emit

        try:
            await emit(
                AgentDBQueryBlocked(
                    tenant_id=str(self.tenant_id),
                    instance_id=self.instance_id,
                    agent_id=self.agent_id,
                    reason=reason,
                    query_hash=query_hash,
                ),
                durable=True,
            )
        except Exception:
            logger.error("agent_db_block_event_failed", exc_info=True)
            from app.agents.security_dlq import enqueue_dead_letter

            await enqueue_dead_letter(
                "db_query_blocked",
                {
                    "tenant_id": str(self.tenant_id),
                    "agent_id": self.agent_id,
                    "reason": reason,
                    "query_hash": query_hash,
                },
            )
