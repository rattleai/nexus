"""Team management endpoints — invitations, members, and role management.

Requires JWT authentication and appropriate role (OWNER or ADMIN for mutations).
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireRole, get_current_user_from_token, get_db
from app.config import settings
from app.core.audit import AuditAction, emit_audit_event
from app.core.events import InvitationSent, emit
from app.db.models import Invitation, InvitationStatus, TenantMembership, User, UserRole

router = APIRouter(prefix="/team")
logger = structlog.stdlib.get_logger()


# ── Schemas ──────────────────────────────────────────────


class InvitationCreate(BaseModel):
    email: EmailStr
    role: str = Field(default="member", pattern=r"^(admin|member|viewer)$")


class InvitationResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: str
    joined_at: datetime

    model_config = {"from_attributes": True}


class MemberUpdate(BaseModel):
    role: str = Field(..., pattern=r"^(admin|member|viewer)$")


class AcceptInvitation(BaseModel):
    token: str
    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=255)


# ── Member endpoints ─────────────────────────────────────


@router.get(
    "/members",
    response_model=list[MemberResponse],
    dependencies=[Depends(RequireRole("owner", "admin", "member", "viewer"))],
)
async def list_members(
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """List all members of the current user's tenant."""
    result = await db.execute(
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.tenant_id == user.tenant_id,
            User.deleted_at.is_(None),
            User.is_active.is_(True),
        )
        .order_by(TenantMembership.created_at.asc())
    )
    rows = result.all()

    return [
        MemberResponse(
            id=membership.id,
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=membership.role.value,
            joined_at=membership.created_at,
        )
        for membership, u in rows
    ]


@router.patch(
    "/members/{user_id}",
    response_model=MemberResponse,
    dependencies=[Depends(RequireRole("owner", "admin"))],
)
async def update_member_role(
    user_id: uuid.UUID,
    body: MemberUpdate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Update a member's role. Only owners can promote to admin."""
    # Prevent self-demotion for owners
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")

    # Get the actor's membership to check permissions
    actor_membership = await db.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user.id,
            TenantMembership.tenant_id == user.tenant_id,
        )
    )
    actor = actor_membership.scalar_one_or_none()
    if not actor:
        raise HTTPException(status_code=403, detail="Not a member of this tenant")

    # Only owners can assign admin role
    new_role = UserRole(body.role)
    if new_role == UserRole.ADMIN and actor.role != UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Only owners can assign admin role")

    # Cannot change an owner's role
    target_membership = await db.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == user.tenant_id,
        )
    )
    target = target_membership.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Cannot change an owner's role")

    old_role = target.role.value
    target.role = new_role

    await emit_audit_event(
        db,
        action=AuditAction.UPDATE,
        resource_type="member",
        resource_id=str(user_id),
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
        changes={"role": [old_role, body.role]},
    )
    await db.commit()

    # Load user info for response
    target_user = await db.execute(select(User).where(User.id == user_id))
    u = target_user.scalar_one()

    logger.info("member_role_updated", user_id=str(user_id), new_role=body.role)
    return MemberResponse(
        id=target.id,
        user_id=u.id,
        email=u.email,
        display_name=u.display_name,
        role=target.role.value,
        joined_at=target.created_at,
    )


@router.delete(
    "/members/{user_id}",
    status_code=204,
    dependencies=[Depends(RequireRole("owner", "admin"))],
)
async def remove_member(
    user_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from the tenant."""
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    membership = await db.execute(
        select(TenantMembership).where(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == user.tenant_id,
        )
    )
    target = membership.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Cannot remove the owner")

    await db.delete(target)
    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="member",
        resource_id=str(user_id),
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
    )
    await db.commit()
    logger.info("member_removed", user_id=str(user_id), tenant_id=str(user.tenant_id))


# ── Invitation endpoints ─────────────────────────────────


@router.post(
    "/invitations",
    response_model=InvitationResponse,
    status_code=201,
    dependencies=[Depends(RequireRole("owner", "admin"))],
)
async def create_invitation(
    body: InvitationCreate,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Invite a user to join the tenant."""
    # Check if user is already a member
    existing_member = await db.execute(
        select(User)
        .join(TenantMembership, TenantMembership.user_id == User.id)
        .where(
            User.email == body.email,
            User.deleted_at.is_(None),
            TenantMembership.tenant_id == user.tenant_id,
        )
    )
    if existing_member.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User is already a member")

    # Check for existing pending invitation
    existing_invite = await db.execute(
        select(Invitation).where(
            Invitation.tenant_id == user.tenant_id,
            Invitation.email == body.email,
            Invitation.status == InvitationStatus.PENDING,
            Invitation.expires_at > datetime.now(UTC),
        )
    )
    if existing_invite.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Invitation already sent to this email")

    # Check member count against plan limits
    from app.billing.enforcement import enforce_plan_limit, get_effective_plan
    from app.core.quotas import QuotaMetric, get_current_usage

    plan = await get_effective_plan(user.tenant_id, db)
    current_users = await get_current_usage(user.tenant_id, QuotaMetric.USERS)
    await enforce_plan_limit(user.tenant_id, plan, QuotaMetric.USERS, current_users)

    # Create invitation
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    invitation = Invitation(
        tenant_id=user.tenant_id,
        email=body.email,
        role=UserRole(body.role),
        invited_by=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invitation)

    await emit_audit_event(
        db,
        action=AuditAction.INVITE,
        resource_type="invitation",
        resource_id=str(invitation.id),
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
        metadata={"email": body.email, "role": body.role},
    )
    await db.commit()
    await db.refresh(invitation)

    accept_url = f"{settings.APP_BASE_URL}/accept-invitation?token={raw_token}"
    await emit(InvitationSent(
        tenant_id=str(user.tenant_id),
        email=body.email,
        role=body.role,
        invited_by=str(user.id),
        accept_url=accept_url,
    ))
    logger.info(
        "invitation_created",
        tenant_id=str(user.tenant_id),
        email=body.email,
        invitation_id=str(invitation.id),
    )

    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role.value,
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


@router.get(
    "/invitations",
    response_model=list[InvitationResponse],
    dependencies=[Depends(RequireRole("owner", "admin"))],
)
async def list_invitations(
    status: str | None = Query(default=None, pattern=r"^(pending|accepted|expired|revoked)$"),
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """List all invitations for the current tenant."""
    stmt = select(Invitation).where(Invitation.tenant_id == user.tenant_id)
    if status:
        stmt = stmt.where(Invitation.status == InvitationStatus(status))
    stmt = stmt.order_by(Invitation.created_at.desc())

    result = await db.execute(stmt)
    invitations = result.scalars().all()

    return [
        InvitationResponse(
            id=inv.id,
            email=inv.email,
            role=inv.role.value,
            status=inv.status.value,
            expires_at=inv.expires_at,
            created_at=inv.created_at,
        )
        for inv in invitations
    ]


@router.delete(
    "/invitations/{invitation_id}",
    status_code=204,
    dependencies=[Depends(RequireRole("owner", "admin"))],
)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a pending invitation."""
    result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.tenant_id == user.tenant_id,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")

    invitation.status = InvitationStatus.REVOKED
    await emit_audit_event(
        db,
        action=AuditAction.REVOKE,
        resource_type="invitation",
        resource_id=str(invitation_id),
        tenant_id=user.tenant_id,
        actor_id=str(user.id),
    )
    await db.commit()
    logger.info("invitation_revoked", invitation_id=str(invitation_id))
