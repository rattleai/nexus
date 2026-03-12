"""MCP tools for team management."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TenantMembership
from app.mcp.errors import tool_error

logger = structlog.stdlib.get_logger()


async def team_list_members(*, tenant: Any, db: AsyncSession) -> list[dict]:
    """List all members of the current tenant's team.

    Returns member names, emails, roles, and join dates.
    """
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(TenantMembership)
        .options(selectinload(TenantMembership.user))
        .where(TenantMembership.tenant_id == tenant.id)
    )
    members = result.scalars().all()

    return [
        {
            "user_id": str(m.user_id),
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
            "email": m.user.email if m.user else None,
            "name": m.user.name if m.user else None,
            "joined_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in members
    ]


async def team_invite(
    email: str,
    role: str = "member",
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Invite a user to the team by email.

    Creates an invitation that the user must accept. Valid roles: member, admin.
    """
    import re

    from app.db.models import Invitation, InvitationStatus

    # Validate email format
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise tool_error(
            "Invalid email address format.",
            hint="Provide a valid email like user@example.com.",
        )

    # Validate role
    valid_roles = {"member", "admin"}
    if role not in valid_roles:
        raise tool_error(
            f"Invalid role: {role}",
            hint=f"Valid roles: {', '.join(sorted(valid_roles))}",
        )

    # Check for existing pending invitation
    existing = await db.execute(
        select(Invitation).where(
            Invitation.tenant_id == tenant.id,
            Invitation.email == email,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    if existing.scalar_one_or_none():
        raise tool_error(
            f"A pending invitation already exists for {email}",
            hint="Wait for the existing invitation to be accepted or revoke it first.",
        )

    from sqlalchemy.exc import IntegrityError

    invitation = Invitation(
        tenant_id=tenant.id,
        email=email,
        role=role,
        status=InvitationStatus.PENDING,
    )
    db.add(invitation)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise tool_error(f"A pending invitation already exists for {email}")
    await db.refresh(invitation)

    logger.info("mcp_team_invite_created", email=email, tenant_id=str(tenant.id))

    return {
        "id": str(invitation.id),
        "email": email,
        "role": role,
        "status": "pending",
    }
