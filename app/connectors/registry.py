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
    ConnectorDefinition,
    ConnectorType,
)

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
    ) -> ConnectorDefinition:
        """Register a custom remote MCP server as a connector definition."""
        from app.core.url_validation import validate_url

        validate_url(url)

        # Generate a slug from the name
        slug = name.lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")

        # Check for duplicate
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
            is_system=False,
            is_active=True,
        )
        db.add(connector)
        await db.flush()

        logger.info(
            "mcp_server_registered",
            slug=slug,
            url=url,
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

    async def sync_builtins(self, db: AsyncSession) -> int:
        """Sync built-in YAML definitions to the database.

        Creates new definitions and updates existing ones.
        Returns the number of definitions synced.
        """
        definitions = self.load_builtins()
        synced = 0

        for data in definitions:
            slug = data.get("slug")
            if not slug:
                logger.warning("builtin_connector_missing_slug", data=data)
                continue

            existing = await self.get_connector(db, slug)

            if existing:
                # Update existing definition
                for key, value in data.items():
                    if key != "slug" and hasattr(existing, key):
                        setattr(existing, key, value)
                existing.is_system = True
            else:
                # Create new definition
                connector = ConnectorDefinition(
                    slug=slug,
                    name=data.get("name", slug),
                    description=data.get("description", ""),
                    icon=data.get("icon", "Plug"),
                    category=data.get("category", "custom"),
                    connector_type=ConnectorType(data["connector_type"]),
                    auth_type=AuthType(data["auth_type"]),
                    auth_config=data.get("auth_config"),
                    mcp_config=data.get("mcp_config"),
                    tool_definitions=data.get("tool_definitions"),
                    webhook_config=data.get("webhook_config"),
                    capability_template=data.get("capability_template"),
                    is_system=True,
                    is_active=True,
                    version=data.get("version", "1.0"),
                    documentation_url=data.get("documentation_url"),
                    tags=data.get("tags", []),
                )
                db.add(connector)

            synced += 1

        # Also load plugin-contributed connector definitions
        try:
            from app.plugins.registry import registry as plugin_registry

            for plugin in plugin_registry:
                if hasattr(plugin, "get_connector_definitions"):
                    for cdata in plugin.get_connector_definitions():
                        pslug = cdata.get("slug")
                        if not pslug:
                            continue
                        existing = await self.get_connector(db, pslug)
                        if not existing:
                            connector = ConnectorDefinition(
                                slug=pslug,
                                name=cdata.get("name", pslug),
                                description=cdata.get("description", ""),
                                icon=cdata.get("icon", "Plug"),
                                category=cdata.get("category", "custom"),
                                connector_type=ConnectorType(cdata["connector_type"]),
                                auth_type=AuthType(cdata["auth_type"]),
                                auth_config=cdata.get("auth_config"),
                                mcp_config=cdata.get("mcp_config"),
                                tool_definitions=cdata.get("tool_definitions"),
                                is_system=True,
                                is_active=True,
                            )
                            db.add(connector)
                            synced += 1
        except Exception:
            logger.debug("plugin_connector_load_skipped", exc_info=True)

        await db.flush()
        self._builtins_loaded = True

        logger.info("connector_builtins_synced", count=synced)
        return synced


# Module-level singleton
connector_registry = ConnectorRegistry()
