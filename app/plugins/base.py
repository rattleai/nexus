"""App plugin protocol and base class.

Each application (CPQ, ERP, CRM, ...) subclasses ``AppPluginBase`` and
exposes a module-level ``PLUGIN`` instance in its ``plugin.py`` file.
The infrastructure discovers these at startup and wires in the
contributed routers, models, MCP tools, scopes, etc.

Import direction contract:
    app.apps.*  may import from  app.core.*, app.db.*, app.ai.*, ...
    app.apps.*  must NEVER import from  other app.apps.*
    Infrastructure must NEVER import from app.apps.* except via the
    plugin registry.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from typing import Callable

if TYPE_CHECKING:
    from fastapi import APIRouter
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from fastmcp import FastMCP
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Agent capability dataclasses ──────────────────────────


@dataclass(frozen=True)
class ToolCapability:
    """A named group of tools representing a single permission scope.

    Used by the capability resolver to map human-friendly scopes
    (e.g. ``cpq:products:write``) to the underlying tool names that
    the agent runtime understands.
    """

    slug: str  # e.g. "cpq:products:write"
    label: str  # e.g. "Create & Edit Products"
    description: str
    tools: tuple[str, ...]  # Tool names this capability grants
    risk_level: str = "low"  # "low" | "medium" | "high" | "critical"
    requires_approval_default: bool = False


@dataclass(frozen=True)
class CapabilityDomain:
    """Top-level grouping of capabilities, typically one per plugin."""

    slug: str  # e.g. "cpq"
    label: str  # e.g. "Product Configurator"
    icon: str  # Lucide icon name
    capabilities: tuple[ToolCapability, ...]


# ── Frontend manifest dataclasses ───────────────────────────


@dataclass(frozen=True)
class NavItem:
    """A sidebar navigation entry contributed by a plugin."""

    href: str
    label_key: str  # i18n translation key
    icon: str  # Lucide icon name (e.g. "Package")
    order: int = 100  # Sort order in sidebar (lower = higher)


@dataclass(frozen=True)
class FrontendManifest:
    """Describes frontend assets a plugin contributes."""

    nav_items: list[NavItem] = field(default_factory=list)


# ── Plugin base class ───────────────────────────────────────


class AppPluginBase(abc.ABC):
    """Concrete base class for application plugins.

    Subclass this and override only the methods your plugin needs.
    All hook methods use **lazy imports** inside the method body to
    prevent circular dependencies — plugin modules are only imported
    when the infrastructure actually wires them up.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique machine-readable name (e.g. ``'cpq'``, ``'erp'``)."""
        ...

    @property
    @abc.abstractmethod
    def version(self) -> str:
        """Semantic version string."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable name for logs and admin UI."""
        return self.name.upper()

    @property
    def feature_flag(self) -> str:
        """Env var that enables/disables this plugin.

        Convention: ``APP_{NAME}_ENABLED`` (e.g. ``APP_CPQ_ENABLED``).
        Default behaviour in the registry: enabled when the variable is
        absent or set to a truthy value.
        """
        return f"APP_{self.name.upper()}_ENABLED"

    # ── Registration hooks ──────────────────────────────────

    def get_routers(self) -> list[APIRouter]:
        """FastAPI routers to mount under ``/api/v1``."""
        return []

    def get_models(self) -> list[type]:
        """SQLAlchemy model classes.

        Importing them is sufficient — they register on
        ``Base.metadata`` automatically.
        """
        return []

    def get_mcp_tools(self, mcp: FastMCP, get_context: Any) -> None:
        """Register MCP tools on the shared ``FastMCP`` server."""

    def get_mcp_bridge_config(self) -> dict[str, Any]:
        """Return ``{"allowed_tags": set, "allowed_path_prefixes": list}``."""
        return {}

    def get_agent_tool_definitions(self) -> dict[str, dict[str, Any]]:
        """Return tool definitions for the agent tool registry."""
        return {}

    def get_capability_domains(self) -> list[CapabilityDomain]:
        """Return capability domains for the agent tool catalog UI.

        The default implementation creates a single domain with one
        ``{name}:all`` capability containing every tool from
        ``get_agent_tool_definitions()``.  Override this method to
        declare granular, human-friendly capability groups.
        """
        tool_defs = self.get_agent_tool_definitions()
        if not tool_defs:
            return []
        return [
            CapabilityDomain(
                slug=self.name,
                label=self.display_name,
                icon="Package",
                capabilities=(
                    ToolCapability(
                        slug=f"{self.name}:all",
                        label=f"All {self.display_name} tools",
                        description=f"Full access to all {self.display_name} capabilities",
                        tools=tuple(tool_defs.keys()),
                    ),
                ),
            ),
        ]

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        tenant: Any,
        db: AsyncSession,
    ) -> Any:
        """Invoke a plugin-owned agent tool by name.

        Called by the agent tool registry when a tool name matches
        one of this plugin's ``get_agent_tool_definitions()`` keys.
        Returns ``None`` if the tool is not handled by this plugin.
        """
        return None

    def get_connector_definitions(self) -> list[dict[str, Any]]:
        """Return connector definitions this plugin contributes.

        Each dict should match the ``ConnectorDefinition`` schema:
        ``slug``, ``name``, ``connector_type``, ``auth_type``, etc.
        """
        return []

    def get_celery_config(self) -> dict[str, Any]:
        """Return ``{"autodiscover": [...], "task_routes": {...}, "beat_schedule": {...}}``."""
        return {}

    def get_scopes(self) -> list[str]:
        """API-key scopes this plugin contributes."""
        return []

    def get_event_handler_modules(self) -> list[str]:
        """Module paths to import for side-effect event handler registration."""
        return []

    def get_frontend_manifest(self) -> FrontendManifest | None:
        """Frontend integration metadata (nav items, etc.)."""
        return None

    def get_error_handlers(self) -> list[tuple[type[Exception], Callable]]:
        """Return ``[(ExceptionClass, handler_fn), ...]`` for plugin-specific errors.

        Handler signature: ``async def handler(request: Request, exc: Exception) -> JSONResponse``
        """
        return []

    def get_plugin_config(self) -> Any:
        """Return the plugin's settings/configuration object."""
        return None

    # ── Lifecycle hooks ─────────────────────────────────────

    async def on_startup(self) -> None:
        """Called during FastAPI lifespan startup, after DB is ready."""

    async def on_shutdown(self) -> None:
        """Called during FastAPI lifespan shutdown."""

    async def health_check(self) -> dict[str, Any]:
        """Return plugin health status.

        Expected keys: ``{"status": "ok"|"degraded"|"unhealthy", ...}``.
        """
        return {"status": "ok"}
