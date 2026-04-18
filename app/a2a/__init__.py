"""Agent2Agent (A2A) protocol support (P3.2).

Architecture-only scaffolding. Implementations plug into the existing
``CredentialBroker`` interface so agents can compose across vendor
platforms (LangGraph ↔ ADK ↔ Crew) without touching the rest of the
codebase. See app/a2a/agent_card.py for the Agent Card publisher and
app/a2a/client.py for the A2A-as-connector adapter.
"""

from app.a2a.agent_card import AgentCard, AgentCapability, publish_agent_card

__all__ = [
    "AgentCard",
    "AgentCapability",
    "publish_agent_card",
]
