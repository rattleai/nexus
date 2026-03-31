"""CPQ plugin manifest.

Discovered by ``app.plugins.registry.discover_plugins()`` at startup.
All heavy imports are deferred inside method bodies to avoid circular
dependencies — the infrastructure only imports this module's ``PLUGIN``
instance at discovery time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from app.plugins.base import (
    AppPluginBase,
    CapabilityDomain,
    FrontendManifest,
    NavItem,
    ToolCapability,
)

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
            },
            "allowed_path_prefixes": [
                "/api/v1/products",
                "/api/v1/characteristics",
                "/api/v1/constraints",
                "/api/v1/boms",
                "/api/v1/configurator",
                "/api/v1/datasources",
            ],
        }

    def get_agent_tool_definitions(self) -> dict[str, dict[str, Any]]:
        from app.apps.cpq.agent_tools import CPQ_TOOL_DEFINITIONS

        return CPQ_TOOL_DEFINITIONS

    def get_capability_domains(self) -> list[CapabilityDomain]:
        return [
            CapabilityDomain(
                slug="cpq",
                label="Product Configurator",
                icon="Package",
                capabilities=(
                    ToolCapability(
                        slug="cpq:products:read",
                        label="View Products",
                        description="List and view product details and product families",
                        tools=("config_list_products", "config_get_product", "config_list_product_families"),
                    ),
                    ToolCapability(
                        slug="cpq:products:write",
                        label="Create & Edit Products",
                        description="Create new products, update existing ones, and manage product families",
                        tools=("config_create_product", "config_update_product", "config_create_product_family"),
                        risk_level="medium",
                    ),
                    ToolCapability(
                        slug="cpq:products:delete",
                        label="Delete Products",
                        description="Permanently remove products from the catalog",
                        tools=("config_delete_product",),
                        risk_level="high",
                        requires_approval_default=True,
                    ),
                    ToolCapability(
                        slug="cpq:characteristics:read",
                        label="View Characteristics",
                        description="List characteristics and characteristic groups",
                        tools=("config_list_characteristics", "config_list_characteristic_groups"),
                    ),
                    ToolCapability(
                        slug="cpq:characteristics:write",
                        label="Manage Characteristics",
                        description="Create characteristics, values, groups, and assign them to products",
                        tools=(
                            "config_create_characteristic",
                            "config_create_characteristic_values",
                            "config_assign_characteristic",
                            "config_create_characteristic_group",
                        ),
                        risk_level="medium",
                    ),
                    ToolCapability(
                        slug="cpq:constraints:read",
                        label="Analyze Constraints",
                        description="Validate constraint models and analyze rule impact",
                        tools=("config_validate_constraints", "config_analyze_constraint_impact"),
                    ),
                    ToolCapability(
                        slug="cpq:constraints:write",
                        label="Manage Constraints",
                        description="Create and update constraint groups and rules",
                        tools=(
                            "config_create_constraint_group",
                            "config_create_constraint_rule",
                            "config_update_constraint_rule",
                        ),
                        risk_level="medium",
                    ),
                    ToolCapability(
                        slug="cpq:constraints:delete",
                        label="Delete Constraints",
                        description="Remove constraint rules",
                        tools=("config_delete_constraint_rule",),
                        risk_level="high",
                    ),
                    ToolCapability(
                        slug="cpq:bom:write",
                        label="Manage BOMs",
                        description="Create BOM headers, add items, batch-create items, and resolve configured BOMs",
                        tools=(
                            "config_create_bom_header",
                            "config_create_bom_item",
                            "config_create_bom_items_batch",
                            "config_resolve_bom",
                        ),
                        risk_level="medium",
                    ),
                    ToolCapability(
                        slug="cpq:pricing:read",
                        label="Simulate Pricing",
                        description="Run pricing simulations for configurations",
                        tools=("config_simulate_pricing",),
                    ),
                    ToolCapability(
                        slug="cpq:pricing:write",
                        label="Manage Pricing Rules",
                        description="Create and update pricing rules",
                        tools=("config_create_pricing_rule", "config_update_pricing_rule"),
                        risk_level="medium",
                    ),
                    ToolCapability(
                        slug="cpq:pricing:delete",
                        label="Delete Pricing Rules",
                        description="Remove pricing rules",
                        tools=("config_delete_pricing_rule",),
                        risk_level="high",
                    ),
                    ToolCapability(
                        slug="cpq:configurator",
                        label="Run Configurator",
                        description="Create configuration sessions, make selections, and simulate configurations",
                        tools=(
                            "config_create_session",
                            "config_get_session",
                            "config_make_selection",
                            "config_list_sessions",
                            "config_simulate_configuration",
                        ),
                    ),
                    ToolCapability(
                        slug="cpq:data",
                        label="Data Sources & Variant Tables",
                        description="Extract documents, search data sources, and manage variant tables",
                        tools=(
                            "config_extract_document",
                            "config_search_datasources",
                            "config_create_variant_table",
                            "config_import_variant_table",
                            "config_list_variant_tables",
                        ),
                        risk_level="medium",
                    ),
                    ToolCapability(
                        slug="cpq:versioning",
                        label="Version Management",
                        description="Create immutable version snapshots of product configurations",
                        tools=("config_create_version_snapshot",),
                        risk_level="medium",
                    ),
                ),
            ),
        ]

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
        ]

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        tenant: Any,
        db: Any,
    ) -> Any:
        """Invoke a CPQ agent tool by name."""
        from app.apps.cpq import mcp_tools as cfg

        handler = getattr(cfg, tool_name, None)
        if handler is None:
            return None
        return await handler(**arguments, tenant=tenant, db=db)

    def get_error_handlers(self) -> list[tuple[type[Exception], Callable]]:
        from fastapi import Request
        from fastapi.responses import JSONResponse

        from app.apps.cpq.exceptions import CPQError

        async def _cpq_error_handler(request: Request, exc: CPQError) -> JSONResponse:
            return JSONResponse(
                status_code=exc.http_status,
                content={
                    "detail": exc.detail,
                    "code": exc.code,
                    "plugin": "cpq",
                },
            )

        return [(CPQError, _cpq_error_handler)]

    def get_plugin_config(self) -> Any:
        from app.apps.cpq.config import cpq_settings

        return cpq_settings

    async def health_check(self) -> dict[str, Any]:
        return {"status": "ok", "engine": "available"}

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
