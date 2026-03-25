"""BOM header and item CRUD endpoints."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.api.schemas_configurator import (
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
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.db.models import BOMHeader, BOMItem, BOMItemType, Product, Tenant

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/boms", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()


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
    await db.commit()
    await db.refresh(bom)
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
    stmt = (
        tenant_query(select(BOMHeader), tenant)
        .where(BOMHeader.product_id == product_id, BOMHeader.deleted_at.is_(None))
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
        tenant_query(select(BOMHeader), tenant).where(
            BOMHeader.id == bom_id, BOMHeader.deleted_at.is_(None)
        )
    )
    bom = result.scalar_one_or_none()
    if not bom:
        raise HTTPException(status_code=404, detail="BOM not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(bom, field, value)
    bom.version += 1
    await db.commit()
    await db.refresh(bom)
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
        tenant_query(select(BOMHeader), tenant).where(
            BOMHeader.id == bom_id, BOMHeader.deleted_at.is_(None)
        )
    )
    bom = result.scalar_one_or_none()
    if not bom:
        raise HTTPException(status_code=404, detail="BOM not found")
    bom.deleted_at = datetime.now(UTC)
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
        tenant_query(select(BOMHeader), tenant).where(
            BOMHeader.id == bom_id, BOMHeader.deleted_at.is_(None)
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="BOM not found")

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
    await db.commit()
    await db.refresh(item)
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

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "item_type":
            item.item_type = BOMItemType(value)
        else:
            setattr(item, field, value)
    item.version += 1
    await db.commit()
    await db.refresh(item)
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
        tenant_query(select(BOMItem), tenant).where(
            BOMItem.bom_header_id == bom_id, BOMItem.deleted_at.is_(None)
        )
    )
    items_by_id = {item.id: item for item in result.scalars().all()}

    for idx, item_id in enumerate(body.item_ids):
        if item_id in items_by_id:
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
        .options(selectinload(BOMItem.bom_header))
    )
    items = result.scalars().all()

    results = []
    for item in items:
        header = item.bom_header
        product_result = await db.execute(select(Product).where(Product.id == header.product_id))
        product = product_result.scalar_one_or_none()
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
