"""Product family and product CRUD endpoints."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.api.schemas_configurator import (
    ProductCreate,
    ProductFamilyCreate,
    ProductFamilyResponse,
    ProductFamilyUpdate,
    ProductResponse,
    ProductUpdate,
    ProductVersionCreate,
    ProductVersionResponse,
)
from app.core.audit import AuditAction, emit_audit_event
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.db.base import optimistic_version_bump
from app.db.models import Product, ProductFamily, ProductStatus, ProductVersion, Tenant

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/products", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()


# ── Product Families ─────────────────────────────────────


@router.post(
    "/families",
    response_model=ProductFamilyResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def create_product_family(
    body: ProductFamilyCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    family = ProductFamily(
        tenant_id=tenant.id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        metadata_=body.metadata or {},
    )
    db.add(family)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="product_family",
        resource_id=str(family.id), tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(family)
    await db.commit()
    return family


@router.get(
    "/families",
    response_model=CursorPage[ProductFamilyResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_product_families(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = tenant_query(select(ProductFamily), tenant).where(ProductFamily.deleted_at.is_(None))
    return await paginate(db, stmt, ProductFamily.created_at, limit=limit, cursor=cursor, descending=True)


@router.get(
    "/families/{family_id}",
    response_model=ProductFamilyResponse,
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def get_product_family(
    family_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ProductFamily), tenant).where(
            ProductFamily.id == family_id, ProductFamily.deleted_at.is_(None)
        )
    )
    family = result.scalar_one_or_none()
    if not family:
        raise HTTPException(status_code=404, detail="Product family not found")
    return family


@router.put(
    "/families/{family_id}",
    response_model=ProductFamilyResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_product_family(
    family_id: uuid.UUID,
    body: ProductFamilyUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ProductFamily), tenant).where(
            ProductFamily.id == family_id, ProductFamily.deleted_at.is_(None)
        )
    )
    family = result.scalar_one_or_none()
    if not family:
        raise HTTPException(status_code=404, detail="Product family not found")

    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if field == "metadata":
            setattr(family, "metadata_", value)
        else:
            setattr(family, field, value)
    await optimistic_version_bump(db, family)
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="product_family",
        resource_id=str(family.id), tenant_id=tenant.id, changes=changes,
    )
    await db.flush()
    await db.refresh(family)
    await db.commit()
    return family


@router.delete(
    "/families/{family_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def delete_product_family(
    family_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ProductFamily), tenant).where(
            ProductFamily.id == family_id, ProductFamily.deleted_at.is_(None)
        )
    )
    family = result.scalar_one_or_none()
    if not family:
        raise HTTPException(status_code=404, detail="Product family not found")
    family.deleted_at = datetime.now(UTC)
    await emit_audit_event(
        db, action=AuditAction.DELETE, resource_type="product_family",
        resource_id=str(family.id), tenant_id=tenant.id,
    )
    await db.commit()


# ── Products ─────────────────────────────────────────────


@router.post(
    "",
    response_model=ProductResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def create_product(
    body: ProductCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    product = Product(
        tenant_id=tenant.id,
        name=body.name,
        slug=body.slug,
        family_id=body.family_id,
        description=body.description,
        sku_prefix=body.sku_prefix,
        status=ProductStatus(body.status),
        metadata_=body.metadata or {},
    )
    db.add(product)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="product",
        resource_id=str(product.id), tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(product)
    await db.commit()
    return product


@router.get(
    "",
    response_model=CursorPage[ProductResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_products(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    family_id: uuid.UUID | None = None,
    status: str | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = tenant_query(select(Product), tenant).where(Product.deleted_at.is_(None))
    if family_id:
        stmt = stmt.where(Product.family_id == family_id)
    if status:
        stmt = stmt.where(Product.status == ProductStatus(status))
    return await paginate(db, stmt, Product.created_at, limit=limit, cursor=cursor, descending=True)


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def get_product(
    product_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(Product), tenant).where(
            Product.id == product_id, Product.deleted_at.is_(None)
        )
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.put(
    "/{product_id}",
    response_model=ProductResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(Product), tenant).where(
            Product.id == product_id, Product.deleted_at.is_(None)
        )
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if field == "metadata":
            setattr(product, "metadata_", value)
        elif field == "status":
            product.status = ProductStatus(value)
        else:
            setattr(product, field, value)
    await optimistic_version_bump(db, product)
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="product",
        resource_id=str(product.id), tenant_id=tenant.id, changes=changes,
    )
    await db.flush()
    await db.refresh(product)
    await db.commit()
    return product


@router.delete(
    "/{product_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def delete_product(
    product_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(Product), tenant).where(
            Product.id == product_id, Product.deleted_at.is_(None)
        )
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.deleted_at = datetime.now(UTC)
    await emit_audit_event(
        db, action=AuditAction.DELETE, resource_type="product",
        resource_id=str(product.id), tenant_id=tenant.id,
    )
    await db.commit()


# ── Product Versions ─────────────────────────────────────


@router.post(
    "/{product_id}/versions",
    response_model=ProductVersionResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def publish_product_version(
    product_id: uuid.UUID,
    body: ProductVersionCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(Product), tenant).where(
            Product.id == product_id, Product.deleted_at.is_(None)
        )
    )
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Get next version number
    max_result = await db.execute(
        select(func.coalesce(func.max(ProductVersion.version_number), 0)).where(
            ProductVersion.product_id == product_id
        )
    )
    next_version = max_result.scalar() + 1

    from app.configurator.snapshot import compile_snapshot
    snapshot = await compile_snapshot(db, product_id, tenant.id)
    snapshot["version_number"] = next_version

    version = ProductVersion(
        tenant_id=tenant.id,
        product_id=product_id,
        version_number=next_version,
        label=body.label,
        snapshot=snapshot,
        is_active=False,
        published_at=datetime.now(UTC),
    )
    db.add(version)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="product_version",
        resource_id=str(version.id), tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(version)
    await db.commit()
    return version


@router.post(
    "/{product_id}/versions/{version_id}/recompile",
    response_model=ProductVersionResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def recompile_product_version(
    product_id: uuid.UUID,
    version_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Recompile the constraint network snapshot for an existing product version."""
    from app.configurator.snapshot import compile_snapshot

    result = await db.execute(
        tenant_query(select(ProductVersion), tenant).where(
            ProductVersion.id == version_id,
            ProductVersion.product_id == product_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")

    snapshot = await compile_snapshot(db, product_id, tenant.id)
    snapshot["version_number"] = version.version_number
    version.snapshot = snapshot

    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="product_version",
        resource_id=str(version.id), tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(version)
    await db.commit()
    return version


@router.get(
    "/{product_id}/versions",
    response_model=list[ProductVersionResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_product_versions(
    product_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ProductVersion), tenant)
        .where(ProductVersion.product_id == product_id)
        .order_by(ProductVersion.version_number.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/{product_id}/versions/{version_id}/activate",
    response_model=ProductVersionResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def activate_product_version(
    product_id: uuid.UUID,
    version_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ProductVersion), tenant).where(
            ProductVersion.id == version_id, ProductVersion.product_id == product_id
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Product version not found")

    # Deactivate all other versions
    all_versions = await db.execute(
        select(ProductVersion).where(ProductVersion.product_id == product_id)
    )
    for v in all_versions.scalars().all():
        v.is_active = False

    version.is_active = True
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="product_version",
        resource_id=str(version.id), tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(version)
    await db.commit()
    return version
