"""P0.2 + P0.3: Per-user token resolution and per-agent authorization."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.agent_bridge import ConnectorToolProvider
from app.connectors.models import ConnectionStatus
from tests.connectors.conftest import make_connection


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def unique(self):
        return self

    def scalars(self):
        return _FakeScalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


def _build_db_with_connections(user_to_connection: dict):
    """Return a mock DB whose execute() filters by connected_by_user_id."""

    def _execute(stmt):  # noqa: ANN001
        # Peek at the compiled SQL to see if there's a user filter
        compiled_sql = str(stmt).lower()
        has_user_filter = "connected_by_user_id" in compiled_sql

        params = stmt.compile().params if hasattr(stmt, "compile") else {}
        user_param = None
        for k, v in params.items():
            if "connected_by_user_id" in str(k).lower():
                user_param = v
                break

        rows = []
        if has_user_filter and user_param is not None:
            uid = uuid.UUID(str(user_param)) if not isinstance(user_param, uuid.UUID) else user_param
            if uid in user_to_connection:
                rows = [user_to_connection[uid]]
        else:
            rows = list(user_to_connection.values())

        return _FakeResult(rows)

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_list_tools_filters_by_user(
    tenant_id, user_a_id, user_b_id, slack_oauth_connector,
):
    conn_a = make_connection(tenant_id, slack_oauth_connector, user_a_id, "alice@x.com")
    conn_b = make_connection(tenant_id, slack_oauth_connector, user_b_id, "bob@x.com")

    db = _build_db_with_connections({user_a_id: conn_a, user_b_id: conn_b})
    provider = ConnectorToolProvider()

    # Patch the Redis cache so every call hits the DB path
    with patch("app.connectors.cache.connector_tool_cache.get_tools", new=AsyncMock(return_value=None)), \
         patch("app.connectors.cache.connector_tool_cache.set_tools", new=AsyncMock()):

        tools_a = await provider.list_tools(
            tenant_id, db, actor_user_id=user_a_id,
        )
        tools_b = await provider.list_tools(
            tenant_id, db, actor_user_id=user_b_id,
        )

    assert all(
        t["connection_id"] == str(conn_a.id) for t in tools_a
    ), "Alice should only see her own connection's tools"
    assert all(
        t["connection_id"] == str(conn_b.id) for t in tools_b
    ), "Bob should only see his own connection's tools"


@pytest.mark.asyncio
async def test_invoke_uses_invoking_user_connection(
    tenant_id, user_a_id, user_b_id, slack_oauth_connector,
):
    conn_a = make_connection(tenant_id, slack_oauth_connector, user_a_id, "alice@x.com")
    conn_b = make_connection(tenant_id, slack_oauth_connector, user_b_id, "bob@x.com")

    db = _build_db_with_connections({user_a_id: conn_a, user_b_id: conn_b})
    provider = ConnectorToolProvider()

    captured_connections = []

    async def fake_broker_invoke(**kwargs):
        captured_connections.append(kwargs["connection"])
        return {"content": "ok", "is_error": False}

    fake_broker = MagicMock()
    fake_broker.invoke_tool = AsyncMock(side_effect=fake_broker_invoke)

    with patch("app.connectors.brokers.router.broker_router.for_connector", return_value=fake_broker):
        await provider.invoke(
            tool_name="connector:slack:list_channels",
            arguments={},
            tenant_id=tenant_id,
            db=db,
            actor_user_id=user_a_id,
        )

    assert len(captured_connections) == 1
    assert captured_connections[0].id == conn_a.id, (
        "Invoke must select the connection whose connected_by_user_id "
        "matches the invoking user — not whichever one is first"
    )


@pytest.mark.asyncio
async def test_invoke_errors_when_user_has_no_connection(
    tenant_id, user_a_id, user_b_id, slack_oauth_connector,
):
    conn_a = make_connection(tenant_id, slack_oauth_connector, user_a_id, "alice@x.com")

    db = _build_db_with_connections({user_a_id: conn_a})
    provider = ConnectorToolProvider()

    result = await provider.invoke(
        tool_name="connector:slack:list_channels",
        arguments={},
        tenant_id=tenant_id,
        db=db,
        actor_user_id=user_b_id,  # Bob has no connection
    )
    assert result["is_error"] is True
    assert "connection" in result["error"].lower()


@pytest.mark.asyncio
async def test_invalid_tool_name_rejected(tenant_id):
    provider = ConnectorToolProvider()
    db = _build_db_with_connections({})
    result = await provider.invoke(
        tool_name="not:a:connector-ish-name",
        arguments={},
        tenant_id=tenant_id,
        db=db,
    )
    # Either the adapter rejects the format, or the DB says "no connection"
    assert result["is_error"] is True
