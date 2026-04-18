"""Connector Tool Adapter: translates between connector and platform tool schemas.

Handles the mapping of MCP tool schemas and API tool definitions to the
platform's unified tool format used by the agent runtime.

Trust-level gating (P0.9) — tool descriptions from UNTRUSTED connectors are
replaced with a generic stub instead of being passed through to the LLM,
preventing indirect prompt-injection via attacker-controlled descriptions
(the class of attack demonstrated by the Invariant Labs GitHub MCP exploit
and documented CVE-2025-6514-style tool poisoning).

Naming convention: ``connector:{connector_slug}:{tool_name}``
"""

from __future__ import annotations

from typing import Any

from app.connectors.models import (
    ConnectorDefinition,
    ConnectorType,
    TenantConnection,
    TrustLevel,
)

# ── Naming ───────────────────────────────────────────────


def make_tool_name(connector_slug: str, tool_name: str) -> str:
    """Build the namespaced tool name used by the agent runtime."""
    return f"connector:{connector_slug}:{tool_name}"


def parse_tool_name(namespaced_name: str) -> tuple[str, str]:
    """Parse ``connector:{slug}:{tool}`` into (slug, tool_name).

    Raises ValueError if the format is invalid.
    """
    parts = namespaced_name.split(":", 2)
    if len(parts) != 3 or parts[0] != "connector":
        raise ValueError(f"Invalid connector tool name: {namespaced_name}")
    return parts[1], parts[2]


# ── Schema Translation ───────────────────────────────────


class ConnectorToolAdapter:
    """Translates connector-native tool schemas to the platform format."""

    @staticmethod
    def mcp_tool_to_platform(
        mcp_tool: dict[str, Any],
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> dict[str, Any]:
        """Convert an MCP tool schema to the platform tool format."""
        tool_name = mcp_tool.get("name", "")
        return {
            "name": make_tool_name(connector_def.slug, tool_name),
            "description": _safe_description(
                mcp_tool.get("description", ""),
                connector_def,
                tool_name,
            ),
            "input_schema": (mcp_tool.get("inputSchema") or mcp_tool.get("input_schema") or {}),
            "source": "connector",
            "connector_slug": connector_def.slug,
            "connector_name": connector_def.name,
            "connector_icon": connector_def.icon,
            "connection_id": str(connection.id),
            "original_tool_name": tool_name,
            "trust_level": connector_def.trust_level.value,
        }

    @staticmethod
    def api_tool_to_platform(
        api_tool: dict[str, Any],
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> dict[str, Any]:
        """Convert an API connector tool definition to the platform format."""
        tool_name = api_tool.get("name", "")
        return {
            "name": make_tool_name(connector_def.slug, tool_name),
            "description": _safe_description(
                api_tool.get("description", ""),
                connector_def,
                tool_name,
            ),
            "input_schema": api_tool.get("input_schema") or {},
            "source": "connector",
            "connector_slug": connector_def.slug,
            "connector_name": connector_def.name,
            "connector_icon": connector_def.icon,
            "connection_id": str(connection.id),
            "original_tool_name": tool_name,
            "trust_level": connector_def.trust_level.value,
        }

    @staticmethod
    def connection_tools_to_platform(
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> list[dict[str, Any]]:
        """Get all platform-formatted tools from a connection."""
        adapter = ConnectorToolAdapter
        tools: list[dict[str, Any]] = []

        if connector_def.connector_type == ConnectorType.MCP_SERVER:
            cached = connection.mcp_tools_cache or []
            for mcp_tool in cached:
                tools.append(adapter.mcp_tool_to_platform(mcp_tool, connection, connector_def))
        else:
            tool_defs = connector_def.tool_definitions or []
            for api_tool in tool_defs:
                tools.append(adapter.api_tool_to_platform(api_tool, connection, connector_def))

        return tools

    @staticmethod
    def normalize_tool_result(raw_result: Any) -> dict[str, Any]:
        """Normalise a connector tool result to the agent-compatible format."""
        if raw_result is None:
            return {"content": "", "is_error": False}

        if isinstance(raw_result, dict):
            return raw_result

        return {"content": str(raw_result), "is_error": False}


# ── Description gating (P0.9) ──────────────────────────


_MAX_DESCRIPTION_LEN = 500


def _safe_description(
    description: str,
    connector_def: ConnectorDefinition,
    tool_name: str,
) -> str:
    """Return a description safe to inject into the LLM system prompt.

    * ``VERIFIED`` — pass through (up to max length).
    * ``TRUSTED`` — pass through, with an explicit provenance note.
    * ``UNTRUSTED`` — replace with a generic stub. The attacker-controlled
      description is never shown to the LLM, so tool-poisoning attacks
      (hidden "ignore previous instructions" markers, embedded system
      prompts, etc.) cannot reach the model.
    """
    connector_name = connector_def.name
    if connector_def.trust_level == TrustLevel.UNTRUSTED:
        return (
            f"{tool_name} — third-party tool from {connector_name}. "
            f"Ask the user before invoking if the request involves "
            f"sensitive data or destructive operations."
        )

    if not description:
        return f"{tool_name} (via {connector_name})"

    if len(description) > _MAX_DESCRIPTION_LEN:
        description = description[: _MAX_DESCRIPTION_LEN - 3] + "..."

    if connector_def.trust_level == TrustLevel.TRUSTED:
        return f"{description}\n[provided by {connector_name} — trusted]"

    return f"{description} (via {connector_name})"
