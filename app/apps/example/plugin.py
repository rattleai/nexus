"""Reference plugin — the smallest functional plugin you can ship.

Reads as a tutorial. Every hook is either implemented with a one-liner or
explicitly delegated to the base class default. Use this file as the
starting point when scaffolding a new application plugin (see
``docs/PLUGINS.md``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.plugins.base import (
    AppPluginBase,
    CapabilityDomain,
    FrontendManifest,
    NavItem,
    ToolCapability,
)

if TYPE_CHECKING:
    from fastapi import APIRouter


class ExamplePlugin(AppPluginBase):
    """Minimal plugin: one HTTP route, one agent tool, one capability."""

    @property
    def name(self) -> str:
        return "example"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def display_name(self) -> str:
        return "Example"

    # ── Registration hooks ──────────────────────────────────

    def get_routers(self) -> list[APIRouter]:
        from app.apps.example.api import router

        return [router]

    def get_agent_tool_definitions(self) -> dict[str, dict[str, Any]]:
        from app.apps.example.agent_tools import EXAMPLE_TOOL_DEFINITIONS

        return EXAMPLE_TOOL_DEFINITIONS

    def get_capability_domains(self) -> list[CapabilityDomain]:
        return [
            CapabilityDomain(
                slug="example",
                label="Example Plugin",
                icon="Package",
                capabilities=(
                    ToolCapability(
                        slug="example:echo",
                        label="Echo tool",
                        description="Use the echo tool. Verifies agent + plugin wiring.",
                        tools=("example_echo",),
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
        db: Any,
    ) -> Any:
        from app.apps.example import agent_tools

        handler = getattr(agent_tools, tool_name, None)
        if handler is None:
            return None
        return await handler(**arguments, tenant=tenant, db=db)

    def get_frontend_manifest(self) -> FrontendManifest | None:
        return FrontendManifest(
            nav_items=[
                NavItem(href="/example", label_key="nav.example", icon="Package", order=90),
            ],
        )

    async def health_check(self) -> dict[str, Any]:
        return {"status": "ok"}


PLUGIN = ExamplePlugin()
