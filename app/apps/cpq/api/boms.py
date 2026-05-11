"""BOM header and item CRUD endpoints."""

import ast
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.apps.cpq.api.schemas_configurator import (
    BOMHeaderCreate,
    BOMHeaderDetailResponse,
    BOMHeaderResponse,
    BOMHeaderUpdate,
    BOMItemCreate,
    BOMItemReorderRequest,
    BOMItemResponse,
    BOMItemUpdate,
    WhereUsedResponse,
)
from app.apps.cpq.models.bom import BOMHeader, BOMItem, BOMItemType
from app.core.audit import AuditAction, emit_audit_event
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.db.base import optimistic_version_bump
from app.db.models import Tenant

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/boms", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()


def _validate_quantity_expression(expr: dict | None) -> None:
    """Validate a quantity_expression JSONB payload before persisting."""
    if expr is None:
        return
    if not isinstance(expr, dict):
        raise HTTPException(status_code=422, detail="quantity_expression must be a JSON object")
    if expr.get("type") != "formula":
        raise HTTPException(status_code=422, detail="quantity_expression.type must be 'formula'")
    formula_str = expr.get("expression")
    if not formula_str or not isinstance(formula_str, str):
        raise HTTPException(status_code=422, detail="quantity_expression.expression is required and must be a string")
    variables = expr.get("variables")
    if not variables or not isinstance(variables, dict):
        raise HTTPException(status_code=422, detail="quantity_expression.variables is required and must be an object")
    try:
        tree = ast.parse(formula_str, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id not in variables:
                raise HTTPException(
                    status_code=422,
                    detail=f"Variable '{node.id}' in expression is not mapped in 'variables'",
                )
    except SyntaxError:
        raise HTTPException(status_code=422, detail=f"quantity_expression.expression has invalid syntax: {formula_str}")


# ── BOM Headers ──────────────────────────────────────────


@router.post(
    "",
    response_model=BOMHeaderResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def create_bom(
    body: BOMHeaderCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    bom = BOMHeader(
        tenant_id=tenant.id,
        product_id=body.product_id,
        name=body.name,
        description=body.description,
        bom_type=body.bom_type,
        is_primary=body.is_primary,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
    )
    db.add(bom)
    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="bom_header",
        resource_id=str(bom.id),
        tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(bom)
    await db.commit()
    return bom


@router.get(
    "",
    response_model=CursorPage[BOMHeaderResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_boms(
    product_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = tenant_query(select(BOMHeader), tenant).where(
        BOMHeader.product_id == product_id, BOMHeader.deleted_at.is_(None)
    )
    return await paginate(db, stmt, BOMHeader.created_at, limit=limit, cursor=cursor, descending=True)


@router.get(
    "/{bom_id}",
    response_model=BOMHeaderDetailResponse,
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def get_bom(
    bom_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(BOMHeader), tenant)
        .where(BOMHeader.id == bom_id, BOMHeader.deleted_at.is_(None))
        .options(selectinload(BOMHeader.items).selectinload(BOMItem.children))
    )
    bom = result.scalar_one_or_none()
    if not bom:
        raise HTTPException(status_code=404, detail="BOM not found")
    return bom


@router.put(
    "/{bom_id}",
    response_model=BOMHeaderResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_bom(
    bom_id: uuid.UUID,
    body: BOMHeaderUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(BOMHeader), tenant).where(BOMHeader.id == bom_id, BOMHeader.deleted_at.is_(None))
    )
    bom = result.scalar_one_or_none()
    if not bom:
        raise HTTPException(status_code=404, detail="BOM not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(bom, field, value)
    await optimistic_version_bump(db, bom)
    await emit_audit_event(
        db,
        action=AuditAction.UPDATE,
        resource_type="bom_header",
        resource_id=str(bom.id),
        tenant_id=tenant.id,
        changes=changes,
    )
    await db.flush()
    await db.refresh(bom)
    await db.commit()
    return bom


@router.delete(
    "/{bom_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def delete_bom(
    bom_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(BOMHeader), tenant).where(BOMHeader.id == bom_id, BOMHeader.deleted_at.is_(None))
    )
    bom = result.scalar_one_or_none()
    if not bom:
        raise HTTPException(status_code=404, detail="BOM not found")
    bom.deleted_at = datetime.now(UTC)
    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="bom_header",
        resource_id=str(bom.id),
        tenant_id=tenant.id,
    )
    await db.commit()


# ── BOM Items ────────────────────────────────────────────


@router.post(
    "/{bom_id}/items",
    response_model=BOMItemResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def add_bom_item(
    bom_id: uuid.UUID,
    body: BOMItemCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(BOMHeader), tenant).where(BOMHeader.id == bom_id, BOMHeader.deleted_at.is_(None))
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="BOM not found")

    _validate_quantity_expression(body.quantity_expression)

    item = BOMItem(
        tenant_id=tenant.id,
        bom_header_id=bom_id,
        parent_item_id=body.parent_item_id,
        item_type=BOMItemType(body.item_type),
        part_number=body.part_number,
        part_name=body.part_name,
        description=body.description,
        quantity=body.quantity,
        quantity_expression=body.quantity_expression,
        unit_of_measure=body.unit_of_measure,
        sub_product_id=body.sub_product_id,
        selection_condition=body.selection_condition,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        sort_order=body.sort_order,
        is_optional=body.is_optional,
        unit_cost=body.unit_cost,
        lead_time_days=body.lead_time_days,
    )
    db.add(item)
    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="bom_item",
        resource_id=str(item.id),
        tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(item, attribute_names=["children"])
    await db.commit()
    return item


@router.put(
    "/{bom_id}/items/{item_id}",
    response_model=BOMItemResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_bom_item(
    bom_id: uuid.UUID,
    item_id: uuid.UUID,
    body: BOMItemUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(BOMItem), tenant).where(
            BOMItem.id == item_id, BOMItem.bom_header_id == bom_id, BOMItem.deleted_at.is_(None)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="BOM item not found")

    update_data = body.model_dump(exclude_unset=True)
    if "quantity_expression" in update_data:
        _validate_quantity_expression(update_data["quantity_expression"])

    for field, value in update_data.items():
        if field == "item_type":
            item.item_type = BOMItemType(value)
        else:
            setattr(item, field, value)
    await optimistic_version_bump(db, item)
    await emit_audit_event(
        db,
        action=AuditAction.UPDATE,
        resource_type="bom_item",
        resource_id=str(item.id),
        tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(item, attribute_names=["children"])
    await db.commit()
    return item


@router.delete(
    "/{bom_id}/items/{item_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def delete_bom_item(
    bom_id: uuid.UUID,
    item_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(BOMItem), tenant).where(
            BOMItem.id == item_id, BOMItem.bom_header_id == bom_id, BOMItem.deleted_at.is_(None)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="BOM item not found")
    item.deleted_at = datetime.now(UTC)
    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="bom_item",
        resource_id=str(item.id),
        tenant_id=tenant.id,
    )
    await db.commit()


@router.post(
    "/{bom_id}/items/reorder",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def reorder_bom_items(
    bom_id: uuid.UUID,
    body: BOMItemReorderRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(BOMItem), tenant).where(BOMItem.bom_header_id == bom_id, BOMItem.deleted_at.is_(None))
    )
    items_by_id = {item.id: item for item in result.scalars().all()}

    unknown_ids = set(body.item_ids) - set(items_by_id.keys())
    if unknown_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Item IDs not found in this BOM: {[str(uid) for uid in unknown_ids]}",
        )

    for idx, item_id in enumerate(body.item_ids):
        items_by_id[item_id].sort_order = idx
    await db.commit()


@router.get(
    "/where-used/{part_number}",
    response_model=list[WhereUsedResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def where_used(
    part_number: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(BOMItem), tenant)
        .where(BOMItem.part_number == part_number, BOMItem.deleted_at.is_(None))
        .options(selectinload(BOMItem.bom_header).selectinload(BOMHeader.product))
    )
    items = result.scalars().all()

    results = []
    for item in items:
        header = item.bom_header
        product = header.product
        results.append(
            WhereUsedResponse(
                bom_header_id=header.id,
                bom_name=header.name,
                product_id=header.product_id,
                product_name=product.name if product else "Unknown",
                item_id=item.id,
                part_number=item.part_number,
                quantity=item.quantity,
            )
        )
    return results
