"""A2A HTTP server scaffolding (P3.2).

FastAPI router that exposes Agent Cards and an A2A ``message/send``
endpoint. Disabled by default (``CONNECTOR_A2A_ENABLED=False``). When
enabled, remote A2A clients can discover and invoke agents via the
Linux Foundation A2A spec.

Full streaming + task cancellation + push notifications are deliberately
left as follow-up work — the architecture hook point is here.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, get_db
from app.config import settings
from app.db.models import Tenant

logger = structlog.stdlib.get_logger()

router = APIRouter(prefix="/a2a", tags=["a2a"])


@router.get("/agents/{agent_id}/.well-known/agent.json")
async def get_agent_card(
    agent_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Return the Agent Card for a tenant-owned agent."""
    if not settings.CONNECTOR_A2A_ENABLED:
        raise HTTPException(status_code=404, detail="A2A is disabled")

    from app.a2a.agent_card import publish_agent_card
    from app.agents.models import AgentDefinition

    agent = await db.get(AgentDefinition, agent_id)
    if agent is None or agent.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Agent not found")

    card = await publish_agent_card(
        agent=agent,
        base_url=settings.APP_BASE_URL,
        db=db,
    )
    return card.to_dict()
