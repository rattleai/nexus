"""Connector registry: catalog, discovery, and built-in loading.

Loads connector definitions from three sources:
    1. Built-in YAML files in ``app/connectors/builtin/``
    2. Plugin contributions via ``AppPluginBase.get_connector_definitions()``
    3. Tenant-defined custom connectors stored in the database

The registry syncs built-in definitions to the database at startup
so they can be queried uniformly.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import (
    AuthType,
    BrokerType,
    ConnectorDefinition,
    ConnectorType,
    TrustLevel,
)

# Fields that must never be stored in the global connector_definitions table.
# They are per-tenant and live in connector_app_credentials, encrypted.
_APP_SECRET_FIELDS = frozenset({"client_id", "client_secret", "webhook_secret"})

logger = structlog.stdlib.get_logger()

BUILTIN_DIR = Path(__file__).parent / "builtin"


class ConnectorRegistry:
    """Discovers and catalogs available connectors."""

    def __init__(self) -> None:
        self._builtins_loaded = False

    # ── Query ────────────────────────────────────────────────

    async def list_connectors(
        self,
        db: AsyncSession,
        *,
        category: str | None = None,
        connector_type: str | None = None,
        search: str | None = None,
        include_inactive: bool = False,
    ) -> list[ConnectorDefinition]:
        """List available connector definitions with optional filters."""
        stmt = select(ConnectorDefinition)

        if not include_inactive:
            stmt = stmt.where(ConnectorDefinition.is_active.is_(True))
        if category:
            stmt = stmt.where(ConnectorDefinition.category == category)
        if connector_type:
            stmt = stmt.where(ConnectorDefinition.connector_type == connector_type)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                ConnectorDefinition.name.ilike(pattern)
                | ConnectorDefinition.description.ilike(pattern)
                | ConnectorDefinition.slug.ilike(pattern)
            )

        stmt = stmt.order_by(ConnectorDefinition.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_connector(
        self,
        db: AsyncSession,
        slug: str,
    ) -> ConnectorDefinition | None:
        """Get a single connector definition by slug."""
        result = await db.execute(
            select(ConnectorDefinition).where(ConnectorDefinition.slug == slug)
        )
        return result.scalar_one_or_none()

    async def get_connector_by_id(
        self,
        db: AsyncSession,
        connector_id: uuid.UUID,
    ) -> ConnectorDefinition | None:
        """Get a single connector definition by ID."""
        return await db.get(ConnectorDefinition, connector_id)

    # ── MCP Server Registration ──────────────────────────────

    async def register_mcp_server(
        self,
        db: AsyncSession,
        *,
        url: str,
        name: str,
        description: str = "",
        tenant_id: uuid.UUID | None = None,
        trust_level: TrustLevel = TrustLevel.UNTRUSTED,
    ) -> ConnectorDefinition:
        """Register a custom remote MCP server as a connector definition."""
        from app.core.url_validation import validate_url

        validate_url(url)

        slug = name.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")

        existing = await self.get_connector(db, slug)
        if existing:
            raise ValueError(f"Connector with slug '{slug}' already exists")

        connector = ConnectorDefinition(
            slug=slug,
            name=name,
            description=description,
            icon="Server",
            category="custom",
            connector_type=ConnectorType.MCP_SERVER,
            auth_type=AuthType.NONE,
            mcp_config={
                "server_url": url,
                "transport": "streamable_http",
            },
            trust_level=trust_level,
            broker=BrokerType.IN_HOUSE,
            is_system=False,
            is_active=True,
        )
        db.add(connector)
        await db.flush()

        logger.info(
            "mcp_server_registered",
            slug=slug,
            url=url,
            trust_level=trust_level.value,
        )
        return connector

    # ── Built-in Sync ────────────────────────────────────────

    def load_builtins(self) -> list[dict[str, Any]]:
        """Load built-in connector definitions from YAML files.

        Returns a list of dicts matching the ConnectorDefinition schema.
        """
        definitions: list[dict[str, Any]] = []

        if not BUILTIN_DIR.exists():
            logger.warning("builtin_connector_dir_missing", path=str(BUILTIN_DIR))
            return definitions

        for yaml_file in sorted(BUILTIN_DIR.glob("*.yaml")):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                if data:
                    definitions.append(data)
            except Exception:
                logger.error(
                    "builtin_connector_load_failed",
                    file=str(yaml_file),
                    exc_info=True,
                )

        return definitions

    # ── Composio Catalog Sync ────────────────────────────────

    async def sync_composio_catalog(self, db: AsyncSession) -> int:
        """Pull Composio's 500+ app catalog into ``connector_definitions``.

        Upserts one row per Composio app with ``broker=composio`` and
        ``trust_level=verified`` (Composio vets the apps it hosts).
        Hand-maintained YAML manifests take precedence by slug — this
        method never clobbers a row that's already marked ``is_system``
        by ``sync_builtins``, so internal / compliance / sensitive
        connectors stay under local control.

        No-ops when Composio is not configured / installed. Call this
        from the lifespan right after ``sync_builtins`` and from the
        ``/connectors/sync-composio`` admin endpoint to pull fresh
        apps without a restart.
        """
        from app.connectors.brokers.composio import (
            _call_async,
            composio_broker,
        )

        if not composio_broker.is_available():
            logger.debug("composio_catalog_sync_skipped_unavailable")
            return 0

        client = composio_broker._client
        if client is None:
            return 0

        try:
            apps = await _call_async(
                getattr(client.apps, "get", client.apps.list),
            )
        except Exception as exc:
            logger.warning(
                "composio_catalog_fetch_failed",
                error=str(exc)[:200],
            )
            return 0

        if apps is None:
            return 0

        # The SDK occasionally returns an object with .items instead of a list
        if hasattr(apps, "items") and callable(apps.items):
            items = list(apps.items())
        elif hasattr(apps, "items"):
            items = list(apps.items)
        else:
            items = list(apps)

        synced = 0
        for app in items:
            slug = self._get_attr(app, "key") or self._get_attr(app, "app_key")
            if not slug:
                continue

            existing = await self.get_connector(db, slug)
            # Protect locally-defined connectors — the YAML always wins.
            if existing is not None and existing.is_system and slug in self._yaml_slugs():
                continue

            name = self._get_attr(app, "name") or slug.title()
            description = self._get_attr(app, "description") or f"{name} via Composio"
            icon = self._get_attr(app, "logo") or "Plug"
            category = self._get_attr(app, "categories")
            if isinstance(category, list) and category:
                category = str(category[0])
            elif not isinstance(category, str):
                category = "productivity"

            auth_schemes = self._get_attr(app, "auth_schemes") or []
            supports_oauth = any(
                "OAUTH" in str(s).upper() for s in auth_schemes
            ) if auth_schemes else True

            data = {
                "slug": slug,
                "name": str(name),
                "description": str(description),
                "icon": str(icon),
                "category": str(category),
                "connector_type": "oauth_api",
                "auth_type": "oauth2" if supports_oauth else "api_key",
                "broker": "composio",
                "trust_level": "verified",
                # Composio manages the shared OAuth apps by default;
                # tenants only register their own if they want dedicated apps.
                "requires_app_credentials": False,
                "version": str(self._get_attr(app, "version") or "1.0"),
                "documentation_url": self._get_attr(app, "docs_url"),
                "tags": self._get_attr(app, "tags") or [],
            }

            if existing is None:
                db.add(self._build_definition(slug, data, is_system=True))
            else:
                # Refresh the catalog metadata but keep local overrides
                self._apply_yaml(existing, data)
                existing.is_system = True

            synced += 1

        await db.flush()
        logger.info("composio_catalog_synced", count=synced)
        return synced

    @staticmethod
    def _get_attr(obj: Any, name: str) -> Any:
        """Dict-or-object field accessor — Composio SDK types shift over versions."""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    def _yaml_slugs(self) -> set[str]:
        """Slugs defined by hand in ``app/connectors/builtin/*.yaml``.

        Cached for the process lifetime — YAML files are deploy-time artifacts.
        """
        if not hasattr(self, "_cached_yaml_slugs"):
            self._cached_yaml_slugs = {
                d.get("slug")
                for d in self.load_builtins()
                if d.get("slug")
            }
        return self._cached_yaml_slugs  # type: ignore[attr-defined]

    async def sync_builtins(self, db: AsyncSession) -> int:
        """Sync built-in YAML definitions to the database.

        Creates new definitions and updates existing ones.
        Strips any ``client_id`` / ``client_secret`` / ``webhook_secret``
        keys from ``auth_config`` and ``webhook_config`` so secrets never
        leak into the global catalog (P0.1).
        """
        definitions = self.load_builtins()
        synced = 0

        for data in definitions:
            slug = data.get("slug")
            if not slug:
                logger.warning("builtin_connector_missing_slug", data=data)
                continue

            self._strip_secrets(data, slug)

            existing = await self.get_connector(db, slug)

            if existing:
                self._apply_yaml(existing, data)
                existing.is_system = True
            else:
                connector = self._build_definition(slug, data, is_system=True)
                db.add(connector)

            synced += 1

        try:
            from app.plugins.registry import registry as plugin_registry

            for plugin in plugin_registry:
                if hasattr(plugin, "get_connector_definitions"):
                    for cdata in plugin.get_connector_definitions():
                        pslug = cdata.get("slug")
                        if not pslug:
                            continue
                        self._strip_secrets(cdata, pslug)
                        existing = await self.get_connector(db, pslug)
                        if not existing:
                            db.add(self._build_definition(pslug, cdata, is_system=True))
                            synced += 1
        except Exception:
            logger.debug("plugin_connector_load_skipped", exc_info=True)

        await db.flush()
        self._builtins_loaded = True

        logger.info("connector_builtins_synced", count=synced)
        return synced

    # ── YAML → Model helpers ─────────────────────────────────

    def _strip_secrets(self, data: dict[str, Any], slug: str) -> None:
        """Remove client_id / client_secret / webhook_secret from YAML data.

        These live in per-tenant ``connector_app_credentials`` only. Logging
        a warning if they appear in YAML makes it obvious during deployment.
        """
        auth = data.get("auth_config")
        if isinstance(auth, dict):
            for key in list(auth.keys()):
                if key in _APP_SECRET_FIELDS:
                    if auth[key]:
                        logger.warning(
                            "yaml_secret_stripped",
                            slug=slug,
                            field=f"auth_config.{key}",
                        )
                    auth.pop(key, None)

        wh = data.get("webhook_config")
        if isinstance(wh, dict) and "secret" in wh:
            if wh["secret"]:
                logger.warning(
                    "yaml_secret_stripped",
                    slug=slug,
                    field="webhook_config.secret",
                )
            wh.pop("secret", None)

    def _apply_yaml(
        self,
        existing: ConnectorDefinition,
        data: dict[str, Any],
    ) -> None:
        """Apply YAML data onto an existing ConnectorDefinition row."""
        existing.name = data.get("name", existing.name)
        existing.description = data.get("description", existing.description or "")
        existing.icon = data.get("icon", existing.icon)
        existing.category = data.get("category", existing.category)
        existing.connector_type = ConnectorType(
            data.get("connector_type", existing.connector_type.value)
        )
        existing.auth_type = AuthType(
            data.get("auth_type", existing.auth_type.value)
        )
        existing.auth_config = data.get("auth_config", existing.auth_config)
        existing.mcp_config = data.get("mcp_config", existing.mcp_config)
        existing.api_config = data.get("api_config", existing.api_config)
        existing.tool_definitions = data.get(
            "tool_definitions", existing.tool_definitions
        )
        existing.webhook_config = data.get("webhook_config", existing.webhook_config)
        existing.capability_template = data.get(
            "capability_template", existing.capability_template
        )
        existing.version = data.get("version", existing.version)
        existing.documentation_url = data.get(
            "documentation_url", existing.documentation_url
        )
        existing.tags = data.get("tags", existing.tags or [])
        if "requires_app_credentials" in data:
            existing.requires_app_credentials = bool(data["requires_app_credentials"])
        if "trust_level" in data:
            try:
                existing.trust_level = TrustLevel(data["trust_level"])
            except ValueError:
                logger.warning(
                    "yaml_invalid_trust_level",
                    slug=existing.slug,
                    value=data.get("trust_level"),
                )
        if "broker" in data:
            try:
                existing.broker = BrokerType(data["broker"])
            except ValueError:
                logger.warning(
                    "yaml_invalid_broker",
                    slug=existing.slug,
                    value=data.get("broker"),
                )

    def _build_definition(
        self,
        slug: str,
        data: dict[str, Any],
        *,
        is_system: bool,
    ) -> ConnectorDefinition:
        """Construct a new ConnectorDefinition row from YAML data."""
        from app.config import settings as _settings

        trust = TrustLevel.UNTRUSTED
        try:
            if "trust_level" in data:
                trust = TrustLevel(data["trust_level"])
            elif is_system:
                trust = TrustLevel.VERIFIED
        except ValueError:
            pass

        # When YAML omits `broker`, fall back to the platform default.
        # Composio is recommended; in-house is the compliance/self-hosted path.
        try:
            default_broker = BrokerType(_settings.CONNECTOR_DEFAULT_BROKER)
        except ValueError:
            default_broker = BrokerType.IN_HOUSE

        broker = default_broker
        try:
            if "broker" in data:
                broker = BrokerType(data["broker"])
        except ValueError:
            pass

        return ConnectorDefinition(
            slug=slug,
            name=data.get("name", slug),
            description=data.get("description", ""),
            icon=data.get("icon", "Plug"),
            category=data.get("category", "custom"),
            connector_type=ConnectorType(data["connector_type"]),
            auth_type=AuthType(data["auth_type"]),
            auth_config=data.get("auth_config"),
            mcp_config=data.get("mcp_config"),
            api_config=data.get("api_config"),
            tool_definitions=data.get("tool_definitions"),
            webhook_config=data.get("webhook_config"),
            capability_template=data.get("capability_template"),
            requires_app_credentials=bool(data.get("requires_app_credentials", False)),
            trust_level=trust,
            broker=broker,
            is_system=is_system,
            is_active=True,
            version=data.get("version", "1.0"),
            documentation_url=data.get("documentation_url"),
            tags=data.get("tags", []),
        )


# Module-level singleton
connector_registry = ConnectorRegistry()
