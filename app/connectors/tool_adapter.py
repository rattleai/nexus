"""Connector Tool Adapter: translates between connector and platform tool schemas.

Handles the mapping of MCP tool schemas and API tool definitions
to the platform's unified tool format used by the agent runtime.

Naming convention: ``connector:{connector_slug}:{tool_name}``
"""

from __future__ import annotations

from typing import Any

from app.connectors.models import ConnectorDefinition, ConnectorType, TenantConnection


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
        """Convert an MCP tool schema to the platform tool format.

        MCP tools have: name, description, inputSchema
        Platform tools have: name, description, input_schema, source, connector_slug, connection_id
        """
        tool_name = mcp_tool.get("name", "")
        return {
            "name": make_tool_name(connector_def.slug, tool_name),
            "description": _sanitize_description(
                mcp_tool.get("description", ""),
                connector_def.name,
                tool_name,
            ),
            "input_schema": mcp_tool.get("inputSchema") or mcp_tool.get("input_schema") or {},
            "source": "connector",
            "connector_slug": connector_def.slug,
            "connector_name": connector_def.name,
            "connector_icon": connector_def.icon,
            "connection_id": str(connection.id),
            "original_tool_name": tool_name,
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
            "description": _sanitize_description(
                api_tool.get("description", ""),
                connector_def.name,
                tool_name,
            ),
            "input_schema": api_tool.get("input_schema") or {},
            "source": "connector",
            "connector_slug": connector_def.slug,
            "connector_name": connector_def.name,
            "connector_icon": connector_def.icon,
            "connection_id": str(connection.id),
            "original_tool_name": tool_name,
        }

    @staticmethod
    def connection_tools_to_platform(
        connection: TenantConnection,
        connector_def: ConnectorDefinition,
    ) -> list[dict[str, Any]]:
        """Get all platform-formatted tools from a connection.

        For MCP connectors: uses cached tools from connection.mcp_tools_cache.
        For API connectors: uses tool_definitions from connector definition.
        """
        adapter = ConnectorToolAdapter
        tools: list[dict[str, Any]] = []

        if connector_def.connector_type == ConnectorType.MCP_SERVER:
            # MCP tools come from the cached discovery
            cached = connection.mcp_tools_cache or []
            for mcp_tool in cached:
                tools.append(
                    adapter.mcp_tool_to_platform(mcp_tool, connection, connector_def)
                )
        else:
            # API tools come from the connector definition
            tool_defs = connector_def.tool_definitions or []
            for api_tool in tool_defs:
                tools.append(
                    adapter.api_tool_to_platform(api_tool, connection, connector_def)
                )

        return tools

    @staticmethod
    def normalize_tool_result(raw_result: Any) -> dict[str, Any]:
        """Normalise a connector tool result to the agent-compatible format.

        The agent runtime expects tool results as dicts or strings.
        """
        if raw_result is None:
            return {"content": "", "is_error": False}

        if isinstance(raw_result, dict):
            return raw_result

        return {"content": str(raw_result), "is_error": False}


# ── Sanitisation ─────────────────────────────────────────


def _sanitize_description(
    description: str,
    connector_name: str,
    tool_name: str,
) -> str:
    """Sanitise a tool description for safe inclusion in LLM prompts.

    Strips potential prompt injection patterns from external MCP server
    tool descriptions while preserving useful information.
    """
    if not description:
        return f"{tool_name} (via {connector_name})"

    # Truncate overly long descriptions
    max_len = 500
    if len(description) > max_len:
        description = description[:max_len] + "..."

    # Strip common prompt injection patterns
    injection_markers = [
        "ignore previous",
        "ignore all",
        "disregard",
        "forget your instructions",
        "system prompt",
        "you are now",
        "new instructions",
        "<system>",
        "</system>",
        "```system",
    ]
    desc_lower = description.lower()
    for marker in injection_markers:
        if marker in desc_lower:
            return f"{tool_name} (via {connector_name}) - [description sanitized]"

    return f"{description} (via {connector_name})"
