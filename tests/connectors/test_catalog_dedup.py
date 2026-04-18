"""Catalog dedup invariants.

Covers the normalize-slug + source-priority dedup logic added so the
marketplace never shows duplicate connector cards when multiple sync
sources (YAML, Composio, plugin, tenant MCP) write into the same
``connector_definitions`` table.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.models import (
    AuthType,
    BrokerType,
    ConnectorDefinition,
    ConnectorSource,
    ConnectorType,
    TrustLevel,
)
from app.connectors.registry import (
    _dedup_by_source_priority,
    connector_registry,
    normalize_slug,
)

# ── Pure helper tests ─────────────────────────────────────


class TestNormalizeSlug:
    def test_lowercase(self):
        assert normalize_slug("SLACK") == "slack"
        assert normalize_slug("Slack") == "slack"

    def test_underscore_to_hyphen(self):
        assert normalize_slug("google_workspace") == "google-workspace"
        assert normalize_slug("my_custom_tool") == "my-custom-tool"

    def test_whitespace_stripped(self):
        assert normalize_slug("  slack  ") == "slack"

    def test_non_alnum_dropped(self):
        assert normalize_slug("slack!@#") == "slack"
        assert normalize_slug("my.cool/tool") == "mycooltool"

    def test_variants_collide(self):
        assert normalize_slug("SLACK_v2") == normalize_slug("slack-v2") == normalize_slug("slack_v2") == "slack-v2"

    def test_empty_input(self):
        assert normalize_slug("") == ""
        assert normalize_slug(None) == ""  # type: ignore[arg-type]

    def test_hyphen_preserved(self):
        assert normalize_slug("google-workspace") == "google-workspace"


# ── YAML slug cache tests ──────────────────────────────────


def test_yaml_canonical_slugs_contains_all_builtins():
    """Every built-in YAML should be discoverable via its canonical slug."""
    canonical = connector_registry._yaml_canonical_slugs()
    # Expected built-ins on this branch
    for expected in (
        "slack",
        "github",
        "notion",
        "linear",
        "jira",
        "google-workspace",
        "dropbox",
        "onedrive",
    ):
        assert expected in canonical, f"missing canonical slug {expected}"


def test_yaml_canonical_slugs_is_normalized():
    """Keys must all be post-normalize form."""
    canonical = connector_registry._yaml_canonical_slugs()
    for key in canonical:
        assert key == normalize_slug(key)


# ── Query-layer dedup tests ────────────────────────────────


def _make_row(slug: str, source: ConnectorSource, name: str = "") -> ConnectorDefinition:
    return ConnectorDefinition(
        id=uuid.uuid4(),
        slug=slug,
        name=name or slug.title(),
        description="",
        icon="Plug",
        category="productivity",
        connector_type=ConnectorType.OAUTH_API,
        auth_type=AuthType.OAUTH2,
        trust_level=TrustLevel.VERIFIED,
        broker=BrokerType.COMPOSIO,
        source=source,
        is_system=True,
        is_active=True,
        version="1.0",
    )


class TestQueryDedup:
    def test_yaml_wins_over_composio(self):
        rows = [
            _make_row("slack", ConnectorSource.COMPOSIO, "Slack (Composio)"),
            _make_row("slack", ConnectorSource.YAML, "Slack"),
        ]
        result = _dedup_by_source_priority(rows)
        assert len(result) == 1
        assert result[0].source == ConnectorSource.YAML
        assert result[0].name == "Slack"

    def test_plugin_wins_over_composio(self):
        rows = [
            _make_row("acme", ConnectorSource.COMPOSIO, "ACME (Composio)"),
            _make_row("acme", ConnectorSource.PLUGIN, "ACME (plugin)"),
        ]
        result = _dedup_by_source_priority(rows)
        assert len(result) == 1
        assert result[0].source == ConnectorSource.PLUGIN

    def test_composio_wins_over_tenant_mcp(self):
        rows = [
            _make_row("hubspot", ConnectorSource.TENANT_MCP, "HubSpot (tenant)"),
            _make_row("hubspot", ConnectorSource.COMPOSIO, "HubSpot (Composio)"),
        ]
        result = _dedup_by_source_priority(rows)
        assert len(result) == 1
        assert result[0].source == ConnectorSource.COMPOSIO

    def test_distinct_slugs_all_kept(self):
        rows = [
            _make_row("slack", ConnectorSource.YAML),
            _make_row("github", ConnectorSource.YAML),
            _make_row("asana", ConnectorSource.COMPOSIO),
        ]
        result = _dedup_by_source_priority(rows)
        assert len(result) == 3

    def test_empty_input(self):
        assert _dedup_by_source_priority([]) == []


# ── Composio sync dedup integration ────────────────────────


class _FakeDB:
    """Minimal async DB stub reused from test_composio_catalog_sync."""

    def __init__(self) -> None:
        self._rows: dict[str, ConnectorDefinition] = {}
        self.flush = AsyncMock()
        self.commit = AsyncMock()

    def add(self, row: ConnectorDefinition) -> None:
        if not row.id:
            row.id = uuid.uuid4()
        self._rows[row.slug] = row

    async def execute(self, stmt):
        result = MagicMock()
        slug = None
        try:
            params = stmt.compile().params if hasattr(stmt, "compile") else {}
            for k, v in params.items():
                if "slug" in str(k).lower():
                    slug = str(v)
                    break
        except Exception:
            pass
        if slug is not None:
            result.scalar_one_or_none.return_value = self._rows.get(slug)
        else:
            scalars = MagicMock()
            scalars.all.return_value = list(self._rows.values())
            result.scalars.return_value = scalars
        return result


class _FakeApp:
    def __init__(self, key: str, name: str = "", description: str = "", aliases=None):
        self.key = key
        self.name = name or key.title()
        self.description = description or f"{key} via Composio"
        self.logo = "Plug"
        self.categories = ["productivity"]
        self.auth_schemes = ["OAUTH2"]
        self.docs_url = None
        self.version = "1.0"
        self.tags = []


@pytest.mark.asyncio
async def test_composio_sync_skips_case_variants_of_yaml():
    """SLACK / slack / Slack must all dedup against the YAML slack entry."""
    db = _FakeDB()
    apps = [
        _FakeApp(key="SLACK", name="Slack (Composio UPPER)"),
        _FakeApp(key="slack", name="Slack (Composio lower)"),
        _FakeApp(key="Slack", name="Slack (Composio Title)"),
    ]
    fake_client = MagicMock()
    fake_client.apps = MagicMock()
    fake_client.apps.get = AsyncMock(return_value=apps)

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

    assert count == 0, "all three variants should be skipped (YAML owns 'slack')"
    assert "slack" not in db._rows  # no Composio row was inserted


@pytest.mark.asyncio
async def test_composio_sync_intra_sync_dedup():
    """Two Composio apps normalizing to the same slug → only the first wins."""
    db = _FakeDB()
    apps = [
        _FakeApp(key="new_provider", name="New Provider v1"),
        _FakeApp(key="new-provider", name="New Provider v2"),
        _FakeApp(key="NEW_PROVIDER", name="New Provider v3"),
    ]
    fake_client = MagicMock()
    fake_client.apps = MagicMock()
    fake_client.apps.get = AsyncMock(return_value=apps)

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
    assert "new-provider" in db._rows
    # First-seen wins
    assert db._rows["new-provider"].name == "New Provider v1"
    assert db._rows["new-provider"].source == ConnectorSource.COMPOSIO


@pytest.mark.asyncio
async def test_composio_sync_respects_alias():
    """If a YAML declares an alias matching a Composio key, skip."""
    db = _FakeDB()
    apps = [_FakeApp(key="gsuite", name="Google Workspace (alt)")]
    fake_client = MagicMock()
    fake_client.apps = MagicMock()
    fake_client.apps.get = AsyncMock(return_value=apps)

    # Inject a fake alias map on the registry for this test
    with (
        patch(
            "app.connectors.brokers.composio.composio_broker.is_available",
            return_value=True,
        ),
        patch(
            "app.connectors.brokers.composio.composio_broker._client",
            fake_client,
        ),
        patch.object(
            connector_registry,
            "_yaml_aliases",
            return_value={"gsuite": "google-workspace"},
        ),
    ):
        count = await connector_registry.sync_composio_catalog(db)

    assert count == 0
    assert "gsuite" not in db._rows


@pytest.mark.asyncio
async def test_composio_sync_accepts_genuinely_new_provider():
    """A Composio app not matching any local slug or alias should be written."""
    db = _FakeDB()
    apps = [_FakeApp(key="asana", name="Asana")]
    fake_client = MagicMock()
    fake_client.apps = MagicMock()
    fake_client.apps.get = AsyncMock(return_value=apps)

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
    row = db._rows["asana"]
    assert row.source == ConnectorSource.COMPOSIO
    assert row.broker == BrokerType.COMPOSIO
    assert row.trust_level == TrustLevel.VERIFIED


# ── register_mcp_server collision guard ────────────────────


@pytest.mark.asyncio
async def test_register_mcp_server_rejects_yaml_collision():
    """Registering a custom MCP server with a name that normalizes to a
    built-in YAML slug must be rejected with a clear error."""
    db = _FakeDB()
    with patch("app.core.url_validation.validate_url", return_value=None):
        with pytest.raises(ValueError, match="built-in"):
            await connector_registry.register_mcp_server(
                db,
                url="https://example.com/mcp",
                name="Slack",
                description="",
            )


@pytest.mark.asyncio
async def test_register_mcp_server_normalizes_custom_name():
    """A legitimate custom name should normalize cleanly and persist."""
    db = _FakeDB()
    with patch("app.core.url_validation.validate_url", return_value=None):
        connector = await connector_registry.register_mcp_server(
            db,
            url="https://example.com/mcp",
            name="My Custom Tool",
            description="A custom MCP server",
        )
    assert connector.slug == "my-custom-tool"
    assert connector.source == ConnectorSource.TENANT_MCP
    assert connector.broker == BrokerType.IN_HOUSE
