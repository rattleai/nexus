"""Composio catalog sync invariants.

Covers the ``sync_composio_catalog`` path without hitting the real
Composio API. The SDK shape varies across versions (sometimes ``apps.get``,
sometimes ``apps.list``; sometimes dataclass, sometimes dict), so these
tests pin behavior on the two shapes the registry supports and verify
the two critical invariants:

1. Hand-maintained YAML slugs are never clobbered by Composio data.
2. When Composio is unavailable the sync is a no-op.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.models import (
    AuthType,
    BrokerType,
    ConnectorDefinition,
    ConnectorType,
    TrustLevel,
)
from app.connectors.registry import connector_registry


@dataclass
class _FakeApp:
    """Shape that mimics Composio SDK's App object."""

    key: str
    name: str
    description: str
    logo: str = "Plug"
    categories: list[str] | None = None
    auth_schemes: list[str] | None = None
    docs_url: str | None = None
    version: str = "1.0"
    tags: list[str] | None = None


class _FakeDB:
    """Minimal async DB stub for registry sync tests."""

    def __init__(self) -> None:
        self._rows: dict[str, ConnectorDefinition] = {}
        self.flush = AsyncMock()
        self.commit = AsyncMock()

    def add(self, row: ConnectorDefinition) -> None:
        if not row.id:
            row.id = uuid.uuid4()
        self._rows[row.slug] = row

    async def execute(self, stmt):  # noqa: ANN001
        result = MagicMock()

        # Parse slug from stmt params
        try:
            params = stmt.compile().params if hasattr(stmt, "compile") else {}
            slug = None
            for k, v in params.items():
                if "slug" in str(k).lower():
                    slug = str(v)
                    break
            if slug is None:
                # Bulk select — return all rows
                rows = list(self._rows.values())
                scalars = MagicMock()
                scalars.all.return_value = rows
                result.scalars.return_value = scalars
                return result
            row = self._rows.get(slug)
        except Exception:
            row = None

        result.scalar_one_or_none.return_value = row
        return result


@pytest.fixture
def fake_apps():
    return [
        _FakeApp(
            key="asana",
            name="Asana",
            description="Task management and team collaboration",
            logo="Target",
            categories=["project_management"],
            auth_schemes=["OAUTH2"],
            docs_url="https://asana.com/api",
        ),
        _FakeApp(
            key="trello",
            name="Trello",
            description="Visual kanban boards",
            categories=["project_management"],
            auth_schemes=["OAUTH2"],
        ),
        _FakeApp(
            key="slack",  # Intentionally collides with a built-in YAML slug
            name="Slack (Composio)",
            description="This should never replace our local Slack manifest",
            categories=["communication"],
        ),
    ]


@pytest.mark.asyncio
async def test_sync_skipped_when_composio_unavailable():
    """Without COMPOSIO_API_KEY the sync is a no-op and does not crash."""
    with patch(
        "app.connectors.brokers.composio.composio_broker.is_available",
        return_value=False,
    ):
        count = await connector_registry.sync_composio_catalog(_FakeDB())
    assert count == 0


@pytest.mark.asyncio
async def test_sync_upserts_new_connectors(fake_apps):
    """Happy path — each Composio app becomes a ConnectorDefinition row."""
    db = _FakeDB()
    fake_client = MagicMock()
    fake_client.apps = MagicMock()
    fake_client.apps.get = AsyncMock(return_value=fake_apps)

    with (
        patch(
            "app.connectors.brokers.composio.composio_broker.is_available",
            return_value=True,
        ),
        patch(
            "app.connectors.brokers.composio.composio_broker._client",
            fake_client,
        ),
    ):
        count = await connector_registry.sync_composio_catalog(db)

    # asana + trello are written; the fake 'slack' entry is skipped
    # at the write layer because it collides with the YAML's slack slug
    # (dedup is now enforced pre-write, not just at query time).
    assert count == 2
    assert "asana" in db._rows
    assert "trello" in db._rows
    assert "slack" not in db._rows  # YAML protects 'slack' from upstream
    asana = db._rows["asana"]
    assert asana.broker == BrokerType.COMPOSIO
    assert asana.trust_level == TrustLevel.VERIFIED
    assert asana.connector_type == ConnectorType.OAUTH_API
    assert asana.auth_type == AuthType.OAUTH2
    assert asana.requires_app_credentials is False  # Composio hosts shared OAuth
    assert asana.is_system is True
    assert asana.category == "project_management"


@pytest.mark.asyncio
async def test_sync_never_clobbers_yaml_slug(fake_apps):
    """Slugs owned by hand-maintained YAMLs are always protected.

    The fixture includes a fake Composio app keyed ``slack`` — the real
    YAML at ``app/connectors/builtin/slack.yaml`` must continue to
    define this connector, and the Composio sync must leave it alone.
    """
    db = _FakeDB()

    # Pre-populate the slack slug the way sync_builtins would have
    from app.connectors.models import ConnectorSource

    local_slack = ConnectorDefinition(
        id=uuid.uuid4(),
        slug="slack",
        name="Slack",
        description="Our local Slack manifest",
        icon="MessageSquare",
        category="communication",
        connector_type=ConnectorType.OAUTH_API,
        auth_type=AuthType.OAUTH2,
        trust_level=TrustLevel.VERIFIED,
        broker=BrokerType.COMPOSIO,
        source=ConnectorSource.YAML,
        is_system=True,
        is_active=True,
        version="1.0.0",
    )
    db.add(local_slack)

    fake_client = MagicMock()
    fake_client.apps = MagicMock()
    fake_client.apps.get = AsyncMock(return_value=fake_apps)

    with (
        patch(
            "app.connectors.brokers.composio.composio_broker.is_available",
            return_value=True,
        ),
        patch(
            "app.connectors.brokers.composio.composio_broker._client",
            fake_client,
        ),
    ):
        await connector_registry.sync_composio_catalog(db)

    preserved = db._rows["slack"]
    assert preserved.description == "Our local Slack manifest", (
        "Composio sync must NOT clobber locally-defined YAML connectors"
    )
    assert preserved.name == "Slack"


@pytest.mark.asyncio
async def test_sync_handles_dict_shaped_apps():
    """Older composio-core versions returned dicts instead of objects."""
    db = _FakeDB()
    dict_apps = [
        {
            "key": "linear_composio",
            "name": "Linear (via dict)",
            "description": "Dict-shaped app",
            "categories": ["project_management"],
            "auth_schemes": ["OAUTH2"],
        }
    ]

    fake_client = MagicMock()
    fake_client.apps = MagicMock()
    fake_client.apps.get = AsyncMock(return_value=dict_apps)

    with (
        patch(
            "app.connectors.brokers.composio.composio_broker.is_available",
            return_value=True,
        ),
        patch(
            "app.connectors.brokers.composio.composio_broker._client",
            fake_client,
        ),
    ):
        count = await connector_registry.sync_composio_catalog(db)

    assert count == 1
    # Slug is normalized on write: linear_composio → linear-composio
    assert "linear-composio" in db._rows
    assert db._rows["linear-composio"].name == "Linear (via dict)"
