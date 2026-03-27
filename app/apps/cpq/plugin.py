"""CPQ plugin manifest.

Discovered by ``app.plugins.registry.discover_plugins()`` at startup.
All heavy imports are deferred inside method bodies to avoid circular
dependencies — the infrastructure only imports this module's ``PLUGIN``
instance at discovery time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.plugins.base import AppPluginBase, FrontendManifest, NavItem

if TYPE_CHECKING:
    from fastapi import APIRouter
    from fastmcp import FastMCP


class CPQPlugin(AppPluginBase):

    @property
    def name(self) -> str:
        return "cpq"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def display_name(self) -> str:
        return "Product Configurator (CPQ)"

    # ── Registration hooks (populated in later phases) ──────

    def get_routers(self) -> list[APIRouter]:
        from app.apps.cpq.api import router

        return [router]

    def get_models(self) -> list[type]:
        from app.apps.cpq.models import ALL_MODELS

        return ALL_MODELS

    def get_mcp_tools(self, mcp: FastMCP, get_context: Any) -> None:
        from app.apps.cpq.mcp_tools import register_cpq_tools

        register_cpq_tools(mcp, get_context)

    def get_mcp_bridge_config(self) -> dict[str, Any]:
        return {
            "allowed_tags": {
                "products",
                "characteristics",
                "constraints",
                "boms",
                "configurator",
                "datasources",
                "cloud-connections",
            },
            "allowed_path_prefixes": [
                "/api/v1/products",
                "/api/v1/characteristics",
                "/api/v1/constraints",
                "/api/v1/boms",
                "/api/v1/configurator",
                "/api/v1/datasources",
                "/api/v1/cloud-connections",
            ],
        }

    def get_agent_tool_definitions(self) -> dict[str, dict[str, Any]]:
        from app.apps.cpq.agent_tools import CPQ_TOOL_DEFINITIONS

        return CPQ_TOOL_DEFINITIONS

    def get_celery_config(self) -> dict[str, Any]:
        return {
            "autodiscover": ["app.apps.cpq.engine"],
        }

    def get_scopes(self) -> list[str]:
        return [
            "configurator:read",
            "configurator:write",
            "datasources:read",
            "datasources:write",
            "cloud-connections:read",
            "cloud-connections:write",
        ]

    def get_frontend_manifest(self) -> FrontendManifest:
        return FrontendManifest(
            nav_items=[
                NavItem(
                    href="/products",
                    label_key="nav.products",
                    icon="Package",
                    order=30,
                ),
                NavItem(
                    href="/configurations",
                    label_key="nav.configurations",
                    icon="ClipboardList",
                    order=40,
                ),
            ],
        )


PLUGIN = CPQPlugin()
