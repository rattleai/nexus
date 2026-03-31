"""Auto-generated capability domains from connector definitions.

For each active connector, generates a ``CapabilityDomain`` with
tool capabilities that can be assigned to agent definitions.

Example for a google-workspace connector::

    CapabilityDomain(
        slug="connectors:google-workspace",
        label="Google Workspace",
        icon="Mail",
        capabilities=(
            ToolCapability(
                slug="connectors:google-workspace:all",
                label="All Google Workspace tools",
                tools=("connector:google-workspace:gmail_send", ...),
            ),
        ),
    )
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.connectors.models import (
    ConnectionStatus,
    ConnectorDefinition,
    ConnectorType,
    TenantConnection,
)
from app.connectors.tool_adapter import ConnectorToolAdapter, make_tool_name
from app.plugins.base import CapabilityDomain, ToolCapability

logger = structlog.stdlib.get_logger()


async def build_connector_capability_domains(
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> list[CapabilityDomain]:
    """Generate capability domains from a tenant's active connections.

    Returns one CapabilityDomain per connected connector, with tool
    capabilities derived from the connector's tools.
    """
    result = await db.execute(
        select(TenantConnection)
        .where(
            TenantConnection.tenant_id == tenant_id,
            TenantConnection.status == ConnectionStatus.ACTIVE,
            TenantConnection.deleted_at.is_(None),
        )
        .options(joinedload(TenantConnection.connector_definition))
    )
    connections = result.unique().scalars().all()

    domains: list[CapabilityDomain] = []

    for conn in connections:
        cd = conn.connector_definition
        if not cd or not cd.is_active:
            continue

        # Get all tool names for this connection
        tools = ConnectorToolAdapter.connection_tools_to_platform(conn, cd)
        tool_names = tuple(t["name"] for t in tools)

        if not tool_names:
            continue

        # Check if the connector definition has a capability template
        template = cd.capability_template or {}
        groups = template.get("groups", [])

        if groups:
            # Use the template to create granular capability groups
            caps: list[ToolCapability] = []
            for group in groups:
                slug_suffix = group.get("slug_suffix", "all")
                patterns = group.get("tool_patterns", [])
                # Filter tools matching patterns (simple prefix match)
                matching = tuple(
                    tn for tn in tool_names
                    if any(p in tn for p in patterns)
                ) if patterns else tool_names
                if matching:
                    caps.append(ToolCapability(
                        slug=f"connectors:{cd.slug}:{slug_suffix}",
                        label=group.get("label", f"{cd.name} {slug_suffix}"),
                        description=group.get("description", ""),
                        tools=matching,
                        risk_level=group.get("risk_level", "low"),
                    ))
            capabilities = tuple(caps)
        else:
            # Default: single "all" capability containing every tool
            capabilities = (
                ToolCapability(
                    slug=f"connectors:{cd.slug}:all",
                    label=f"All {cd.name} tools",
                    description=f"Full access to all {cd.name} capabilities",
                    tools=tool_names,
                ),
            )

        domains.append(CapabilityDomain(
            slug=f"connectors:{cd.slug}",
            label=cd.name,
            icon=cd.icon,
            capabilities=capabilities,
        ))

    return domains
