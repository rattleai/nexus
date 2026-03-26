"""Characteristic, group, value, and assignment CRUD endpoints."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.configurator.engine import ConfiguratorEngine
from app.core.audit import AuditAction, emit_audit_event
from app.api.schemas_configurator import (
    CharacteristicAssignmentCreate,
    CharacteristicAssignmentResponse,
    CharacteristicAssignmentUpdate,
    CharacteristicCreate,
    CharacteristicGroupCreate,
    CharacteristicGroupResponse,
    CharacteristicGroupUpdate,
    CharacteristicResponse,
    CharacteristicUpdate,
    CharacteristicValueCreate,
    CharacteristicValueResponse,
    CharacteristicValueUpdate,
)
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.db.base import optimistic_version_bump
from app.db.models import (
    Characteristic,
    CharacteristicAssignment,
    CharacteristicGroup,
    CharacteristicType,
    CharacteristicValue,
    Product,
    Tenant,
)

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/characteristics", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()


# ── Groups ───────────────────────────────────────────────


@router.post(
    "/groups",
    response_model=CharacteristicGroupResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def create_group(
    body: CharacteristicGroupCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    group = CharacteristicGroup(
        tenant_id=tenant.id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        display_order=body.display_order,
    )
    db.add(group)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="characteristic_group",
        resource_id=str(group.id), tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(group)
    return group


@router.get(
    "/groups",
    response_model=CursorPage[CharacteristicGroupResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_groups(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = tenant_query(select(CharacteristicGroup), tenant).where(
        CharacteristicGroup.deleted_at.is_(None)
    )
    return await paginate(db, stmt, CharacteristicGroup.created_at, limit=limit, cursor=cursor, descending=True)


@router.put(
    "/groups/{group_id}",
    response_model=CharacteristicGroupResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_group(
    group_id: uuid.UUID,
    body: CharacteristicGroupUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(CharacteristicGroup), tenant).where(
            CharacteristicGroup.id == group_id, CharacteristicGroup.deleted_at.is_(None)
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Characteristic group not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(group, field, value)
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="characteristic_group",
        resource_id=str(group.id), tenant_id=tenant.id, changes=changes,
    )
    await db.commit()
    await db.refresh(group)
    return group


@router.delete(
    "/groups/{group_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def delete_group(
    group_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(CharacteristicGroup), tenant).where(
            CharacteristicGroup.id == group_id, CharacteristicGroup.deleted_at.is_(None)
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Characteristic group not found")
    group.deleted_at = datetime.now(UTC)
    await emit_audit_event(
        db, action=AuditAction.DELETE, resource_type="characteristic_group",
        resource_id=str(group.id), tenant_id=tenant.id,
    )
    await db.commit()


# ── Characteristics ──────────────────────────────────────


@router.post(
    "",
    response_model=CharacteristicResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def create_characteristic(
    body: CharacteristicCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    char = Characteristic(
        tenant_id=tenant.id,
        name=body.name,
        slug=body.slug,
        group_id=body.group_id,
        description=body.description,
        char_type=CharacteristicType(body.char_type),
        numeric_min=body.numeric_min,
        numeric_max=body.numeric_max,
        numeric_step=body.numeric_step,
        unit=body.unit,
        is_required=body.is_required,
        is_multi_select=body.is_multi_select,
        default_value=body.default_value,
        display_order=body.display_order,
    )
    db.add(char)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="characteristic",
        resource_id=str(char.id), tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(char, attribute_names=["values"])
    return char


@router.get(
    "",
    response_model=CursorPage[CharacteristicResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_characteristics(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    group_id: uuid.UUID | None = None,
    char_type: str | None = None,
    product_id: uuid.UUID | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        tenant_query(select(Characteristic), tenant)
        .where(Characteristic.deleted_at.is_(None))
        .options(selectinload(Characteristic.values))
    )
    if group_id:
        stmt = stmt.where(Characteristic.group_id == group_id)
    if char_type:
        stmt = stmt.where(Characteristic.char_type == CharacteristicType(char_type))
    if product_id:
        stmt = stmt.where(
            Characteristic.id.in_(
                select(CharacteristicAssignment.characteristic_id).where(
                    CharacteristicAssignment.product_id == product_id
                )
            )
        )
    return await paginate(db, stmt, Characteristic.created_at, limit=limit, cursor=cursor, descending=True)


@router.get(
    "/{char_id}",
    response_model=CharacteristicResponse,
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def get_characteristic(
    char_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(Characteristic), tenant)
        .where(Characteristic.id == char_id, Characteristic.deleted_at.is_(None))
        .options(selectinload(Characteristic.values))
    )
    char = result.scalar_one_or_none()
    if not char:
        raise HTTPException(status_code=404, detail="Characteristic not found")
    return char


@router.put(
    "/{char_id}",
    response_model=CharacteristicResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_characteristic(
    char_id: uuid.UUID,
    body: CharacteristicUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(Characteristic), tenant)
        .where(Characteristic.id == char_id, Characteristic.deleted_at.is_(None))
        .options(selectinload(Characteristic.values))
    )
    char = result.scalar_one_or_none()
    if not char:
        raise HTTPException(status_code=404, detail="Characteristic not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(char, field, value)
    await optimistic_version_bump(db, char)
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="characteristic",
        resource_id=str(char.id), tenant_id=tenant.id, changes=changes,
    )
    await db.commit()
    await db.refresh(char, attribute_names=["values"])
    return char


@router.delete(
    "/{char_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def delete_characteristic(
    char_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(Characteristic), tenant).where(
            Characteristic.id == char_id, Characteristic.deleted_at.is_(None)
        )
    )
    char = result.scalar_one_or_none()
    if not char:
        raise HTTPException(status_code=404, detail="Characteristic not found")
    char.deleted_at = datetime.now(UTC)
    await emit_audit_event(
        db, action=AuditAction.DELETE, resource_type="characteristic",
        resource_id=str(char.id), tenant_id=tenant.id,
    )
    await db.commit()


# ── Values ───────────────────────────────────────────────


@router.post(
    "/{char_id}/values",
    response_model=CharacteristicValueResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def add_value(
    char_id: uuid.UUID,
    body: CharacteristicValueCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(Characteristic), tenant).where(
            Characteristic.id == char_id, Characteristic.deleted_at.is_(None)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Characteristic not found")

    val = CharacteristicValue(
        tenant_id=tenant.id,
        characteristic_id=char_id,
        value=body.value,
        label=body.label,
        description=body.description,
        display_order=body.display_order,
        is_default=body.is_default,
        price_adjustment=body.price_adjustment,
        image_url=body.image_url,
    )
    db.add(val)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="characteristic_value",
        resource_id=str(val.id), tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(val)
    return val


@router.put(
    "/{char_id}/values/{value_id}",
    response_model=CharacteristicValueResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_value(
    char_id: uuid.UUID,
    value_id: uuid.UUID,
    body: CharacteristicValueUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(CharacteristicValue), tenant).where(
            CharacteristicValue.id == value_id,
            CharacteristicValue.characteristic_id == char_id,
        )
    )
    val = result.scalar_one_or_none()
    if not val:
        raise HTTPException(status_code=404, detail="Characteristic value not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(val, field, value)
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="characteristic_value",
        resource_id=str(val.id), tenant_id=tenant.id, changes=changes,
    )
    await db.commit()
    await db.refresh(val)
    return val


@router.delete(
    "/{char_id}/values/{value_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def delete_value(
    char_id: uuid.UUID,
    value_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(CharacteristicValue), tenant).where(
            CharacteristicValue.id == value_id,
            CharacteristicValue.characteristic_id == char_id,
        )
    )
    val = result.scalar_one_or_none()
    if not val:
        raise HTTPException(status_code=404, detail="Characteristic value not found")
    await emit_audit_event(
        db, action=AuditAction.DELETE, resource_type="characteristic_value",
        resource_id=str(val.id), tenant_id=tenant.id,
    )
    await db.delete(val)
    await db.commit()


# ── Assignments ──────────────────────────────────────────


@router.post(
    "/assign",
    response_model=CharacteristicAssignmentResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def assign_characteristic(
    body: CharacteristicAssignmentCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Validate product exists
    product_result = await db.execute(
        tenant_query(select(Product), tenant).where(
            Product.id == body.product_id, Product.deleted_at.is_(None)
        )
    )
    if not product_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")
    # Validate characteristic exists
    char_result = await db.execute(
        tenant_query(select(Characteristic), tenant).where(
            Characteristic.id == body.characteristic_id, Characteristic.deleted_at.is_(None)
        )
    )
    if not char_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Characteristic not found")

    assignment = CharacteristicAssignment(
        tenant_id=tenant.id,
        product_id=body.product_id,
        characteristic_id=body.characteristic_id,
        display_order=body.display_order,
        is_required=body.is_required,
        default_value=body.default_value,
        min_select=body.min_select,
        max_select=body.max_select,
    )
    db.add(assignment)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="characteristic_assignment",
        resource_id=str(assignment.id), tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(assignment)
    ConfiguratorEngine.invalidate_product_cache(body.product_id, tenant.id)
    return assignment


@router.get(
    "/assign",
    response_model=list[CharacteristicAssignmentResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_assignments(
    product_id: uuid.UUID = Query(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(CharacteristicAssignment), tenant).where(
            CharacteristicAssignment.product_id == product_id
        ).order_by(CharacteristicAssignment.display_order)
    )
    return result.scalars().all()


@router.put(
    "/assign/{assignment_id}",
    response_model=CharacteristicAssignmentResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_assignment(
    assignment_id: uuid.UUID,
    body: CharacteristicAssignmentUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(CharacteristicAssignment), tenant).where(
            CharacteristicAssignment.id == assignment_id
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(assignment, key, value)

    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="characteristic_assignment",
        resource_id=str(assignment.id), tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(assignment)
    ConfiguratorEngine.invalidate_product_cache(assignment.product_id, tenant.id)
    return assignment


@router.delete(
    "/assign/{assignment_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def remove_assignment(
    assignment_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(CharacteristicAssignment), tenant).where(
            CharacteristicAssignment.id == assignment_id
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    product_id = assignment.product_id
    await emit_audit_event(
        db, action=AuditAction.DELETE, resource_type="characteristic_assignment",
        resource_id=str(assignment.id), tenant_id=tenant.id,
    )
    await db.delete(assignment)
    await db.commit()
    ConfiguratorEngine.invalidate_product_cache(product_id, tenant.id)
