"""Capability resolver — maps capability slugs to tool names.

Provides the bridge between the human-friendly capability model
(domains and scopes like ``cpq:products:write``) and the flat tool
name lists consumed by the agent runtime.

The capability catalog is built from:
    1. Platform built-in capabilities (from ``tool_registry.PLATFORM_CAPABILITIES``)
    2. Plugin-declared capabilities (from each plugin's ``get_capability_domains()``)

The index is built once per process and cached.  It has **no database
dependency** — capabilities are declared in code, not stored in the DB.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.plugins.base import CapabilityDomain, ToolCapability

logger = structlog.stdlib.get_logger()


class CapabilityResolver:
    """Resolves capability slugs to flat tool name sets.

    Usage::

        from app.agents.capabilities import capability_resolver

        tools = capability_resolver.resolve(["cpq:products:read", "platform:ai"])
        # → {"config_list_products", "config_get_product", ..., "ai_complete", "ai_list_models"}
    """

    def __init__(self) -> None:
        self._slug_to_tools: dict[str, tuple[str, ...]] | None = None
        self._tool_to_slug: dict[str, str] | None = None
        self._domains: list[CapabilityDomain] | None = None

    def _build_index(self) -> None:
        """Build the capability → tools index from all sources."""
        from app.agents.tool_registry import PLATFORM_CAPABILITIES
        from app.plugins.registry import registry as plugin_registry

        slug_to_tools: dict[str, tuple[str, ...]] = {}
        tool_to_slug: dict[str, str] = {}
        domains: list[CapabilityDomain] = [PLATFORM_CAPABILITIES]

        # Platform capabilities
        for cap in PLATFORM_CAPABILITIES.capabilities:
            slug_to_tools[cap.slug] = cap.tools
            for tool_name in cap.tools:
                tool_to_slug[tool_name] = cap.slug

        # Plugin capabilities
        for plugin in plugin_registry:
            try:
                plugin_domains = plugin.get_capability_domains()
                for domain in plugin_domains:
                    domains.append(domain)
                    for cap in domain.capabilities:
                        slug_to_tools[cap.slug] = cap.tools
                        for tool_name in cap.tools:
                            tool_to_slug[tool_name] = cap.slug
            except Exception:
                logger.warning(
                    "capability_domain_load_failed",
                    plugin=plugin.name,
                    exc_info=True,
                )

        self._slug_to_tools = slug_to_tools
        self._tool_to_slug = tool_to_slug
        self._domains = domains

    def _ensure_index(self) -> None:
        if self._slug_to_tools is None:
            self._build_index()

    def resolve(self, capability_slugs: list[str]) -> set[str]:
        """Resolve a list of capability slugs to a set of tool names."""
        self._ensure_index()
        assert self._slug_to_tools is not None  # ensured above
        tools: set[str] = set()
        for slug in capability_slugs:
            if slug in self._slug_to_tools:
                tools.update(self._slug_to_tools[slug])
            else:
                logger.debug("capability_slug_unknown", slug=slug)
        return tools

    def resolve_agent_tools(self, definition: Any) -> list[str]:
        """Get the effective tool list for an agent definition.

        Resolution logic:
            - If ``definition.capabilities`` is non-empty, resolve those to
              tool names and union with ``definition.allowed_tools``.
            - If ``definition.capabilities`` is empty, fall back to
              ``definition.allowed_tools`` only (legacy behaviour).

        Returns a deduplicated, sorted list of tool names.
        """
        capabilities = getattr(definition, "capabilities", None) or []
        allowed_tools = getattr(definition, "allowed_tools", None) or []

        if capabilities:
            tools = self.resolve(capabilities)
            tools.update(allowed_tools)
            return sorted(tools)

        # Legacy: no capabilities configured, use raw allowed_tools
        return list(allowed_tools)

    def get_catalog(self) -> list[CapabilityDomain]:
        """Return the full capability catalog (platform + all plugins)."""
        self._ensure_index()
        assert self._domains is not None
        return list(self._domains)

    def get_capability_for_tool(self, tool_name: str) -> str | None:
        """Reverse lookup: which capability slug contains this tool?"""
        self._ensure_index()
        assert self._tool_to_slug is not None
        return self._tool_to_slug.get(tool_name)

    def invalidate(self) -> None:
        """Clear the cached index (e.g. after hot-reloading plugins in tests)."""
        self._slug_to_tools = None
        self._tool_to_slug = None
        self._domains = None


# Module-level singleton
capability_resolver = CapabilityResolver()
