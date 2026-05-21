"""A2A Agent Card publisher (P3.2).

Exposes each ``AgentDefinition`` as an A2A Agent Card at
``/a2a/agents/{id}/.well-known/agent.json``. Remote A2A clients can
discover the agent's capabilities, supported modalities, and endpoints
via this card.

The Agent Card format follows the Linux Foundation A2A spec. We stay
minimal — full A2A server + streaming negotiation is a later follow-up.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentDefinition


@dataclass
class AgentCapability:
    name: str
    description: str
    input_modalities: list[str] = field(default_factory=lambda: ["text"])
    output_modalities: list[str] = field(default_factory=lambda: ["text"])


@dataclass
class AgentCard:
    name: str
    description: str
    url: str
    version: str
    provider: str
    capabilities: list[AgentCapability] = field(default_factory=list)
    supported_features: dict[str, bool] = field(
        default_factory=lambda: {
            "streaming": True,
            "push_notifications": False,
            "state_updates": True,
        }
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
        }


async def publish_agent_card(
    *,
    agent: AgentDefinition,
    base_url: str,
    db: AsyncSession,
) -> AgentCard:
    """Build an A2A Agent Card for an agent definition."""
    capabilities: list[AgentCapability] = []
    for slug in agent.capabilities or []:
        capabilities.append(
            AgentCapability(
                name=str(slug),
                description=f"Capability: {slug}",
            )
        )

    return AgentCard(
        name=agent.name,
        description=agent.description or "",
        url=f"{base_url.rstrip('/')}/a2a/agents/{agent.id}",
        version=str(getattr(agent, "version", 1)),
        provider="nxs",
        capabilities=capabilities,
        metadata={
            "tenant_id": str(agent.tenant_id),
            "model": agent.model,
        },
    )
