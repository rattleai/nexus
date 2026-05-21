"""Connector registry: catalog, discovery, and built-in loading.

Loads connector definitions from three sources:
    1. Built-in YAML files in ``app/connectors/builtin/``
    2. Plugin contributions via ``AppPluginBase.get_connector_definitions()``
    3. Tenant-defined custom connectors stored in the database

The registry syncs built-in definitions to the database at startup
so they can be queried uniformly.
"""

from __future__ import annotations

import re
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
    ConnectorSource,
    ConnectorType,
    TrustLevel,
)

# Fields that must never be stored in the global connector_definitions table.
# They are per-tenant and live in connector_app_credentials, encrypted.
_APP_SECRET_FIELDS = frozenset({"client_id", "client_secret", "webhook_secret"})

logger = structlog.stdlib.get_logger()

BUILTIN_DIR = Path(__file__).parent / "builtin"

# ── Slug canonicalization ───────────────────────────────────

_SLUG_WORD_SEP = re.compile(r"[\s_]+")
_SLUG_ALNUM_HYPHEN = re.compile(r"[^a-z0-9-]")
_SLUG_COLLAPSE_HYPHENS = re.compile(r"-{2,}")


def normalize_slug(raw: str) -> str:
    """Canonicalize a connector slug for collision checks.

    * Lowercases.
    * Collapses any run of whitespace or underscores into a single hyphen
      (so ``"My Custom Tool"`` → ``"my-custom-tool"`` and ``"SLACK_v2"`` →
      ``"slack-v2"``).
    * Drops any remaining non-alphanumeric, non-hyphen character.
    * Collapses runs of hyphens and trims leading/trailing hyphens.

    Empty input returns ``""``.
    """
    if not raw:
        return ""
    s = raw.strip().lower()
    # Internal whitespace and underscores become hyphens (word separators)
    s = _SLUG_WORD_SEP.sub("-", s)
    # Drop anything not alphanumeric or hyphen
    s = _SLUG_ALNUM_HYPHEN.sub("", s)
    # Collapse consecutive hyphens and trim
    s = _SLUG_COLLAPSE_HYPHENS.sub("-", s).strip("-")
    return s


# Source priority for query-layer dedup: lower number = higher priority.
# yaml wins over plugin wins over composio wins over tenant_mcp.
_SOURCE_PRIORITY: dict[str, int] = {
    ConnectorSource.YAML.value: 0,
    ConnectorSource.PLUGIN.value: 1,
    ConnectorSource.COMPOSIO.value: 2,
    ConnectorSource.TENANT_MCP.value: 3,
}


def _dedup_by_source_priority(
    rows: list[ConnectorDefinition],
) -> list[ConnectorDefinition]:
    """Return at most one row per normalized slug, preferring higher priority.

    The write-path already prevents collisions, but we defend in depth here
    so a pre-existing data load or a bug never leaks duplicate cards into
    the marketplace UI.
    """
    best: dict[str, ConnectorDefinition] = {}
    for row in rows:
        canonical = normalize_slug(row.slug)
        if not canonical:
            continue
        current = best.get(canonical)
        if current is None:
            best[canonical] = row
            continue
        current_pri = _SOURCE_PRIORITY.get(
            current.source.value if hasattr(current.source, "value") else str(current.source),
            99,
        )
        new_pri = _SOURCE_PRIORITY.get(
            row.source.value if hasattr(row.source, "value") else str(row.source),
            99,
        )
        if new_pri < current_pri:
            best[canonical] = row
    # Preserve the original ordering (by name) — sort by first-seen position
    original_index = {id(r): i for i, r in enumerate(rows)}
    return sorted(best.values(), key=lambda r: original_index.get(id(r), 0))


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
        """List available connector definitions with optional filters.

        Applies a query-layer dedup pass as defense-in-depth: if two rows
        share a normalized slug (should be prevented at write time, but we
        guard anyway), the higher-priority ``source`` wins. Priority order
        is ``yaml > plugin > composio > tenant_mcp``.
        """
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
        rows = list(result.scalars().all())
        return _dedup_by_source_priority(rows)

    async def get_connector(
        self,
        db: AsyncSession,
        slug: str,
    ) -> ConnectorDefinition | None:
        """Get a single connector definition by slug."""
        result = await db.execute(select(ConnectorDefinition).where(ConnectorDefinition.slug == slug))
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

        canonical = normalize_slug(name)
        if not canonical:
            raise ValueError("Connector name must contain at least one alphanumeric character")

        # Can't shadow a YAML/plugin/Composio-owned connector by name
        if canonical in self._yaml_canonical_slugs():
            raise ValueError(
                f"Connector name '{name}' collides with built-in slug '{canonical}'. Pick a different name."
            )
        if canonical in self._yaml_aliases():
            owner = self._yaml_aliases()[canonical]
            raise ValueError(
                f"Connector name '{name}' collides with built-in connector "
                f"'{owner}' (via alias). Pick a different name."
            )

        existing = await self.get_connector(db, canonical)
        if existing:
            raise ValueError(f"Connector with slug '{canonical}' already exists")

        connector = ConnectorDefinition(
            slug=canonical,
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
            source=ConnectorSource.TENANT_MCP,
            is_system=False,
            is_active=True,
        )
        db.add(connector)
        await db.flush()

        logger.info(
            "mcp_server_registered",
            slug=canonical,
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

        yaml_canonical = self._yaml_canonical_slugs()
        yaml_aliases = self._yaml_aliases()
        seen_this_sync: set[str] = set()

        synced = 0
        skipped_yaml = 0
        skipped_alias = 0
        skipped_intra = 0
        for app in items:
            raw_slug = self._get_attr(app, "key") or self._get_attr(app, "app_key")
            if not raw_slug:
                continue

            canonical = normalize_slug(str(raw_slug))
            if not canonical:
                continue

            # Local YAML wins
            if canonical in yaml_canonical:
                skipped_yaml += 1
                logger.debug(
                    "composio_catalog_skipped_yaml_wins",
                    raw_slug=raw_slug,
                    canonical=canonical,
                )
                continue

            # Explicit alias match
            if canonical in yaml_aliases:
                skipped_alias += 1
                logger.debug(
                    "composio_catalog_skipped_alias",
                    raw_slug=raw_slug,
                    canonical=canonical,
                    yaml_slug=yaml_aliases[canonical],
                )
                continue

            # Intra-sync dedup — first seen wins
            if canonical in seen_this_sync:
                skipped_intra += 1
                logger.debug(
                    "composio_catalog_skipped_intra_sync_dup",
                    raw_slug=raw_slug,
                    canonical=canonical,
                )
                continue
            seen_this_sync.add(canonical)

            existing = await self.get_connector(db, canonical)
            # Only overwrite rows we own. YAML/plugin/tenant_mcp rows are
            # foreign and must not be clobbered by a Composio sync.
            if existing is not None and existing.source != ConnectorSource.COMPOSIO:
                skipped_yaml += 1
                logger.debug(
                    "composio_catalog_skipped_foreign_source",
                    canonical=canonical,
                    source=existing.source.value if hasattr(existing.source, "value") else existing.source,
                )
                continue

            name = self._get_attr(app, "name") or canonical.replace("-", " ").title()
            description = self._get_attr(app, "description") or f"{name} via Composio"
            icon = self._get_attr(app, "logo") or "Plug"
            category = self._get_attr(app, "categories")
            if isinstance(category, list) and category:
                category = str(category[0])
            elif not isinstance(category, str):
                category = "productivity"

            auth_schemes = self._get_attr(app, "auth_schemes") or []
            supports_oauth = any("OAUTH" in str(s).upper() for s in auth_schemes) if auth_schemes else True

            data = {
                "slug": canonical,
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
                new_row = self._build_definition(canonical, data, is_system=True)
                new_row.source = ConnectorSource.COMPOSIO
                db.add(new_row)
            else:
                # Refresh the catalog metadata but keep local overrides
                self._apply_yaml(existing, data)
                existing.is_system = True
                existing.source = ConnectorSource.COMPOSIO

            synced += 1

        await db.flush()
        logger.info(
            "composio_catalog_synced",
            count=synced,
            skipped_yaml=skipped_yaml,
            skipped_alias=skipped_alias,
            skipped_intra=skipped_intra,
        )
        return synced

    @staticmethod
    def _get_attr(obj: Any, name: str) -> Any:
        """Dict-or-object field accessor — Composio SDK types shift over versions."""
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    def _yaml_canonical_slugs(self) -> dict[str, str]:
        """Return ``{normalized_slug: original_slug}`` for every built-in YAML.

        Cached for the process lifetime — YAML files are deploy-time
        artifacts. Callers use this map both to detect slug collisions
        (via ``normalized_slug in self._yaml_canonical_slugs()``) and to
        look up the YAML's canonical form when a Composio app matches.
        """
        if not hasattr(self, "_cached_yaml_canonical_slugs"):
            mapping: dict[str, str] = {}
            for d in self.load_builtins():
                raw_slug = d.get("slug")
                if not raw_slug:
                    continue
                canonical = normalize_slug(raw_slug)
                if not canonical:
                    continue
                if canonical in mapping and mapping[canonical] != raw_slug:
                    # Two YAML files normalize to the same slug — that's a
                    # deploy-time configuration bug, not runtime drift.
                    raise RuntimeError(
                        f"Duplicate normalized YAML slug '{canonical}' between '{mapping[canonical]}' and '{raw_slug}'"
                    )
                mapping[canonical] = raw_slug
            self._cached_yaml_canonical_slugs = mapping
        return self._cached_yaml_canonical_slugs  # type: ignore[attr-defined]

    def _yaml_aliases(self) -> dict[str, str]:
        """Return ``{normalized_alias: canonical_yaml_slug}`` for all YAMLs.

        Lets Composio apps whose key matches a local alias be deduplicated
        against the YAML owning that alias. Example::

            google-workspace.yaml:
              slug: google-workspace
              aliases: [google_workspace, gsuite, googleworkspace]

        ⇒ ``{"google-workspace": "google-workspace", "gsuite": "google-workspace",
             "googleworkspace": "google-workspace"}``
        """
        if not hasattr(self, "_cached_yaml_aliases"):
            mapping: dict[str, str] = {}
            for d in self.load_builtins():
                raw_slug = d.get("slug")
                if not raw_slug:
                    continue
                canonical = normalize_slug(raw_slug)
                for alias in d.get("aliases") or []:
                    normalized_alias = normalize_slug(str(alias))
                    if not normalized_alias:
                        continue
                    if normalized_alias in mapping and mapping[normalized_alias] != canonical:
                        logger.warning(
                            "yaml_alias_collision",
                            alias=normalized_alias,
                            existing=mapping[normalized_alias],
                            new=canonical,
                        )
                        continue
                    mapping[normalized_alias] = canonical
            self._cached_yaml_aliases = mapping
        return self._cached_yaml_aliases  # type: ignore[attr-defined]

    async def sync_builtins(self, db: AsyncSession) -> int:
        """Sync built-in YAML definitions to the database.

        Normalizes each YAML slug, ensures no two YAMLs collide after
        normalization (`_yaml_canonical_slugs` raises at load time if they
        do), strips any ``client_id`` / ``client_secret`` / ``webhook_secret``
        keys so secrets never leak into the global catalog, and marks every
        row with ``source=ConnectorSource.YAML`` so query-layer dedup can
        give them top priority.
        """
        definitions = self.load_builtins()
        synced = 0

        for data in definitions:
            raw_slug = data.get("slug")
            if not raw_slug:
                logger.warning("builtin_connector_missing_slug", data=data)
                continue

            canonical = normalize_slug(raw_slug)
            if not canonical:
                logger.warning("builtin_connector_empty_slug", raw=raw_slug)
                continue

            # Canonicalize in-place so downstream helpers see the
            # normalized form.
            data["slug"] = canonical
            self._strip_secrets(data, canonical)

            existing = await self.get_connector(db, canonical)

            if existing:
                self._apply_yaml(existing, data)
                existing.is_system = True
                existing.source = ConnectorSource.YAML
            else:
                connector = self._build_definition(canonical, data, is_system=True)
                connector.source = ConnectorSource.YAML
                db.add(connector)

            synced += 1

        try:
            from app.plugins.registry import registry as plugin_registry

            for plugin in plugin_registry:
                if hasattr(plugin, "get_connector_definitions"):
                    for cdata in plugin.get_connector_definitions():
                        raw_pslug = cdata.get("slug")
                        if not raw_pslug:
                            continue
                        pslug = normalize_slug(raw_pslug)
                        if not pslug:
                            continue
                        cdata["slug"] = pslug
                        self._strip_secrets(cdata, pslug)
                        existing = await self.get_connector(db, pslug)
                        if not existing:
                            row = self._build_definition(pslug, cdata, is_system=True)
                            row.source = ConnectorSource.PLUGIN
                            db.add(row)
                            synced += 1
                        else:
                            # A plugin can register an enrichment for an
                            # existing row (e.g. update description), but
                            # never silently downgrade source priority.
                            if existing.source in (
                                ConnectorSource.YAML,
                                ConnectorSource.PLUGIN,
                            ):
                                self._apply_yaml(existing, cdata)
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
        existing.connector_type = ConnectorType(data.get("connector_type", existing.connector_type.value))
        existing.auth_type = AuthType(data.get("auth_type", existing.auth_type.value))
        existing.auth_config = data.get("auth_config", existing.auth_config)
        existing.mcp_config = data.get("mcp_config", existing.mcp_config)
        existing.api_config = data.get("api_config", existing.api_config)
        existing.tool_definitions = data.get("tool_definitions", existing.tool_definitions)
        existing.webhook_config = data.get("webhook_config", existing.webhook_config)
        existing.capability_template = data.get("capability_template", existing.capability_template)
        existing.version = data.get("version", existing.version)
        existing.documentation_url = data.get("documentation_url", existing.documentation_url)
        existing.tags = data.get("tags", existing.tags or [])
        if "aliases" in data:
            existing.aliases = [
                normalize_slug(str(a)) for a in data.get("aliases") or [] if normalize_slug(str(a))
            ] or None
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

        normalized_aliases = [
            normalize_slug(str(a)) for a in data.get("aliases") or [] if normalize_slug(str(a))
        ] or None

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
            aliases=normalized_aliases,
            is_system=is_system,
            is_active=True,
            version=data.get("version", "1.0"),
            documentation_url=data.get("documentation_url"),
            tags=data.get("tags", []),
        )


# Module-level singleton
connector_registry = ConnectorRegistry()
