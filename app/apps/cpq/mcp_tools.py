"""MCP tools for product configuration domain operations.

These tools enable AI agents to create and manage configurable products,
characteristics, constraint rules, BOMs, variant tables, and pricing rules.
Each handler wraps the same service-layer logic used by the REST API endpoints.

The ``register_cpq_tools`` function at the bottom registers these handlers
as MCP tools on the shared FastMCP server instance. It is called by the
CPQ plugin's ``get_mcp_tools`` method during startup.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, emit_audit_event

logger = structlog.stdlib.get_logger()


# ── Shared validation helpers ─────────────────────────────────────────


def _parse_uuid(value: str, field: str) -> uuid.UUID | dict:
    """Parse a UUID string, returning an error dict on failure."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        return {"error": f"Invalid {field}: must be a valid UUID"}


def _parse_enum(value: str, enum_cls: type, field: str) -> Any | dict:
    """Parse an enum value, returning an error dict on failure."""
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        valid = [e.value for e in enum_cls]
        return {"error": f"Invalid {field}: must be one of {valid}"}


def _clamp_limit(limit: int, maximum: int = 100) -> int:
    return max(1, min(limit, maximum))


# ── Product Tools ─────────────────────────────────────────────────────


async def config_create_product(
    name: str,
    slug: str,
    description: str = "",
    sku_prefix: str = "",
    family_id: str | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a new configurable product."""
    from app.db.models.product import Product, ProductStatus

    if family_id:
        fid = _parse_uuid(family_id, "family_id")
        if isinstance(fid, dict):
            return fid
    else:
        fid = None

    product = Product(
        tenant_id=tenant.id,
        name=name,
        slug=slug,
        description=description or "",
        sku_prefix=sku_prefix or "",
        family_id=fid,
        status=ProductStatus.DRAFT,
    )
    db.add(product)
    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="product", resource_id=str(product.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(product)

    logger.info("config_product_created", product_id=str(product.id), name=name)
    return {"id": str(product.id), "name": product.name, "slug": product.slug, "status": product.status.value}


async def config_list_products(
    status: str | None = None,
    limit: int = 50,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """List products for the tenant."""
    from app.db.models.product import Product, ProductStatus

    limit = _clamp_limit(limit)
    stmt = select(Product).where(
        Product.tenant_id == tenant.id,
        Product.deleted_at.is_(None),
    )
    if status:
        s = _parse_enum(status, ProductStatus, "status")
        if isinstance(s, dict):
            return s
        stmt = stmt.where(Product.status == s)
    stmt = stmt.order_by(Product.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    products = result.scalars().all()

    return {
        "products": [
            {"id": str(p.id), "name": p.name, "slug": p.slug, "status": p.status.value}
            for p in products
        ],
        "count": len(products),
    }


async def config_get_product(
    product_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Get product with characteristics, constraints, and BOMs."""
    from app.db.models.bom import BOMHeader
    from app.db.models.product import (
        CharacteristicAssignment,
        ConstraintRule,
        Product,
    )

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    stmt = select(Product).where(
        Product.id == pid,
        Product.tenant_id == tenant.id,
        Product.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        return {"error": f"Product {product_id} not found"}

    # Load assignments with characteristics
    assign_stmt = (
        select(CharacteristicAssignment)
        .options(selectinload(CharacteristicAssignment.characteristic))
        .where(
            CharacteristicAssignment.product_id == pid,
            CharacteristicAssignment.tenant_id == tenant.id,
        )
        .order_by(CharacteristicAssignment.display_order)
    )
    assign_result = await db.execute(assign_stmt)
    assignments = assign_result.scalars().all()

    # Load constraints
    rule_stmt = select(ConstraintRule).where(
        ConstraintRule.product_id == pid,
        ConstraintRule.tenant_id == tenant.id,
        ConstraintRule.deleted_at.is_(None),
    )
    rule_result = await db.execute(rule_stmt)
    rules = rule_result.scalars().all()

    # Load BOMs
    bom_stmt = select(BOMHeader).where(
        BOMHeader.product_id == pid,
        BOMHeader.tenant_id == tenant.id,
        BOMHeader.deleted_at.is_(None),
    )
    bom_result = await db.execute(bom_stmt)
    boms = bom_result.scalars().all()

    return {
        "id": str(product.id),
        "name": product.name,
        "slug": product.slug,
        "status": product.status.value,
        "characteristics": [
            {
                "id": str(a.characteristic.id),
                "name": a.characteristic.name,
                "slug": a.characteristic.slug,
                "char_type": a.characteristic.char_type.value,
                "is_required": a.is_required if a.is_required is not None else a.characteristic.is_required,
                "display_order": a.display_order,
            }
            for a in assignments
            if a.characteristic
        ],
        "constraints": [
            {
                "id": str(r.id),
                "name": r.name,
                "constraint_type": r.constraint_type.value,
                "expression": r.expression,
                "priority": r.priority,
            }
            for r in rules
        ],
        "boms": [
            {"id": str(b.id), "name": b.name, "is_primary": b.is_primary}
            for b in boms
        ],
    }


# ── Characteristic Tools ──────────────────────────────────────────────


async def config_create_characteristic(
    name: str,
    slug: str,
    char_type: str,
    group_id: str | None = None,
    values: list[dict] | None = None,
    numeric_min: float | None = None,
    numeric_max: float | None = None,
    numeric_step: float | None = None,
    unit: str | None = None,
    is_required: bool = False,
    is_multi_select: bool = False,
    default_value: str | None = None,
    description: str = "",
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a characteristic with optional values."""
    from app.db.models.product import Characteristic, CharacteristicType, CharacteristicValue

    ct = _parse_enum(char_type, CharacteristicType, "char_type")
    if isinstance(ct, dict):
        return ct

    gid = None
    if group_id:
        gid = _parse_uuid(group_id, "group_id")
        if isinstance(gid, dict):
            return gid

    try:
        nmin = Decimal(str(numeric_min)) if numeric_min is not None else None
        nmax = Decimal(str(numeric_max)) if numeric_max is not None else None
        nstep = Decimal(str(numeric_step)) if numeric_step is not None else None
    except InvalidOperation:
        return {"error": "Invalid numeric value for numeric_min, numeric_max, or numeric_step"}

    char = Characteristic(
        tenant_id=tenant.id,
        name=name,
        slug=slug,
        description=description,
        char_type=ct,
        group_id=gid,
        numeric_min=nmin,
        numeric_max=nmax,
        numeric_step=nstep,
        unit=unit,
        is_required=is_required,
        is_multi_select=is_multi_select,
        default_value=default_value,
    )
    db.add(char)
    await db.flush()

    # Create values for enum type
    created_values = []
    if values and char_type == "enum":
        for i, val_data in enumerate(values):
            cv = CharacteristicValue(
                tenant_id=tenant.id,
                characteristic_id=char.id,
                value=val_data["value"],
                label=val_data.get("label", val_data["value"]),
                description=val_data.get("description", ""),
                is_default=val_data.get("is_default", False),
                price_adjustment=Decimal(str(val_data["price_adjustment"])) if val_data.get("price_adjustment") else None,
                display_order=i,
            )
            db.add(cv)
            created_values.append({"value": cv.value, "label": cv.label})

    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="characteristic", resource_id=str(char.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(char)

    logger.info("config_characteristic_created", char_id=str(char.id), name=name, values_count=len(created_values))
    return {
        "id": str(char.id),
        "name": char.name,
        "slug": char.slug,
        "char_type": char.char_type.value,
        "values": created_values,
    }


async def config_create_characteristic_values(
    characteristic_id: str,
    values: list[dict],
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Batch-create values for an enum characteristic."""
    from app.db.models.product import Characteristic, CharacteristicValue

    char_id = _parse_uuid(characteristic_id, "characteristic_id")
    if isinstance(char_id, dict):
        return char_id
    char = await db.get(Characteristic, char_id)
    if not char or char.tenant_id != tenant.id:
        return {"error": f"Characteristic {characteristic_id} not found"}

    # Get current max display_order
    stmt = select(CharacteristicValue).where(
        CharacteristicValue.characteristic_id == char_id,
        CharacteristicValue.tenant_id == tenant.id,
    )
    existing = (await db.execute(stmt)).scalars().all()
    max_order = max((v.display_order for v in existing), default=-1)

    created = []
    for i, val_data in enumerate(values):
        cv = CharacteristicValue(
            tenant_id=tenant.id,
            characteristic_id=char_id,
            value=val_data["value"],
            label=val_data.get("label", val_data["value"]),
            description=val_data.get("description", ""),
            is_default=val_data.get("is_default", False),
            price_adjustment=Decimal(str(val_data["price_adjustment"])) if val_data.get("price_adjustment") else None,
            display_order=max_order + 1 + i,
        )
        db.add(cv)
        created.append({"id": str(cv.id), "value": cv.value, "label": cv.label})

    await db.commit()

    return {"characteristic_id": characteristic_id, "values_created": len(created), "values": created}


async def config_assign_characteristic(
    product_id: str,
    characteristic_id: str,
    display_order: int = 0,
    is_required: bool | None = None,
    default_value: str | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Assign a characteristic to a product."""
    from app.db.models.product import CharacteristicAssignment

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid
    cid = _parse_uuid(characteristic_id, "characteristic_id")
    if isinstance(cid, dict):
        return cid

    assignment = CharacteristicAssignment(
        tenant_id=tenant.id,
        product_id=pid,
        characteristic_id=cid,
        display_order=display_order,
        is_required=is_required,
        default_value=default_value,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    return {
        "id": str(assignment.id),
        "product_id": product_id,
        "characteristic_id": characteristic_id,
        "display_order": display_order,
    }


async def config_list_characteristics(
    product_id: str | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """List characteristics, optionally filtered by product."""
    from app.db.models.product import Characteristic, CharacteristicAssignment, CharacteristicValue

    if product_id:
        pid = _parse_uuid(product_id, "product_id")
        if isinstance(pid, dict):
            return pid
        # List characteristics assigned to this product
        stmt = (
            select(CharacteristicAssignment)
            .options(
                selectinload(CharacteristicAssignment.characteristic)
                .selectinload(Characteristic.values)
            )
            .where(
                CharacteristicAssignment.product_id == pid,
                CharacteristicAssignment.tenant_id == tenant.id,
            )
            .order_by(CharacteristicAssignment.display_order)
        )
        result = await db.execute(stmt)
        assignments = result.scalars().all()

        return {
            "characteristics": [
                {
                    "id": str(a.characteristic.id),
                    "name": a.characteristic.name,
                    "slug": a.characteristic.slug,
                    "char_type": a.characteristic.char_type.value,
                    "is_required": a.is_required if a.is_required is not None else a.characteristic.is_required,
                    "values": [
                        {"value": v.value, "label": v.label}
                        for v in sorted(a.characteristic.values, key=lambda x: x.display_order)
                    ] if a.characteristic.char_type.value == "enum" else [],
                }
                for a in assignments
                if a.characteristic
            ],
        }
    else:
        # List all tenant characteristics
        stmt = (
            select(Characteristic)
            .options(selectinload(Characteristic.values))
            .where(
                Characteristic.tenant_id == tenant.id,
                Characteristic.deleted_at.is_(None),
            )
            .order_by(Characteristic.name)
            .limit(100)
        )
        result = await db.execute(stmt)
        chars = result.scalars().all()

        return {
            "characteristics": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "slug": c.slug,
                    "char_type": c.char_type.value,
                    "values": [
                        {"value": v.value, "label": v.label}
                        for v in sorted(c.values, key=lambda x: x.display_order)
                    ] if c.char_type.value == "enum" else [],
                }
                for c in chars
            ],
        }


# ── Constraint Tools ──────────────────────────────────────────────────


async def config_create_constraint_group(
    product_id: str,
    name: str,
    description: str = "",
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a constraint group."""
    from app.db.models.product import ConstraintGroup

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    group = ConstraintGroup(
        tenant_id=tenant.id,
        product_id=pid,
        name=name,
        description=description,
    )
    db.add(group)
    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="constraint_group", resource_id=str(group.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(group)

    return {"id": str(group.id), "name": group.name, "product_id": product_id}


async def config_create_constraint_rule(
    product_id: str,
    name: str,
    constraint_type: str,
    expression: dict,
    group_id: str | None = None,
    description: str = "",
    priority: int = 10,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a constraint rule with JSONB AST expression."""
    from app.db.models.product import ConstraintRule, ConstraintType

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid
    ct = _parse_enum(constraint_type, ConstraintType, "constraint_type")
    if isinstance(ct, dict):
        return ct
    gid = None
    if group_id:
        gid = _parse_uuid(group_id, "group_id")
        if isinstance(gid, dict):
            return gid

    rule = ConstraintRule(
        tenant_id=tenant.id,
        product_id=pid,
        name=name,
        description=description,
        constraint_type=ct,
        expression=expression,
        group_id=gid,
        priority=priority,
        is_active=True,
    )
    db.add(rule)
    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="constraint_rule", resource_id=str(rule.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(rule)

    logger.info("config_constraint_created", rule_id=str(rule.id), name=name, type=constraint_type)
    return {
        "id": str(rule.id),
        "name": rule.name,
        "constraint_type": rule.constraint_type.value,
        "product_id": product_id,
    }


async def config_validate_constraints(
    product_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Run constraint analyzer on a product."""
    from app.apps.cpq.engine.analyzer import ConstraintAnalyzer

    analyzer = ConstraintAnalyzer(db)
    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    try:
        result = await analyzer.analyze(product_id=pid, tenant_id=tenant.id)
        return {
            "valid": result.get("is_valid", True),
            "cycles": result.get("cycles", []),
            "dead_values": result.get("dead_values", []),
            "coverage_gaps": result.get("coverage_gaps", []),
            "rule_count": result.get("rule_count", 0),
            "summary": result.get("summary", "Analysis complete"),
        }
    except Exception as exc:
        return {"error": f"Constraint validation failed: {exc}"}


async def config_simulate_configuration(
    product_id: str,
    selections: dict[str, str],
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Simulate constraint propagation with trial selections."""
    from app.apps.cpq.engine.engine import ConfiguratorEngine

    engine = ConfiguratorEngine(db)
    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    try:
        result = await engine.simulate(
            product_id=pid,
            tenant_id=tenant.id,
            selections=selections,
        )
        return {
            "is_valid": result.get("is_valid", False),
            "available_domains": result.get("available_domains", {}),
            "auto_set": result.get("auto_set", {}),
            "excluded_values": result.get("excluded_values", {}),
            "contradictions": result.get("contradictions", []),
            "conflict_explanations": result.get("conflict_explanations", []),
        }
    except Exception as exc:
        return {"error": f"Simulation failed: {exc}"}


async def config_analyze_constraint_impact(
    product_id: str,
    rule_expression: dict,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Analyze the impact of a constraint rule expression."""
    from app.apps.cpq.engine.analyzer import ConstraintAnalyzer

    analyzer = ConstraintAnalyzer(db)
    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    try:
        result = await analyzer.impact_analysis(
            product_id=pid,
            tenant_id=tenant.id,
            expression=rule_expression,
        )
        return result
    except Exception as exc:
        return {"error": f"Impact analysis failed: {exc}"}


# ── BOM Tools ─────────────────────────────────────────────────────────


async def config_create_bom_header(
    product_id: str,
    name: str,
    description: str = "",
    bom_type: str = "manufacturing",
    is_primary: bool = True,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a 150% super BOM header."""
    from app.db.models.bom import BOMHeader

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    bom = BOMHeader(
        tenant_id=tenant.id,
        product_id=pid,
        name=name,
        description=description,
        bom_type=bom_type,
        is_primary=is_primary,
    )
    db.add(bom)
    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="bom_header", resource_id=str(bom.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(bom)

    logger.info("config_bom_created", bom_id=str(bom.id), name=name)
    return {"id": str(bom.id), "name": bom.name, "product_id": product_id, "is_primary": bom.is_primary}


async def config_create_bom_item(
    bom_header_id: str,
    part_number: str,
    part_name: str,
    quantity: float = 1.0,
    selection_condition: dict | None = None,
    item_type: str = "component",
    parent_item_id: str | None = None,
    description: str = "",
    unit_of_measure: str = "EA",
    unit_cost: float | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Add a BOM item with optional selection condition."""
    from app.db.models.bom import BOMHeader, BOMItem, BOMItemType

    hid = _parse_uuid(bom_header_id, "bom_header_id")
    if isinstance(hid, dict):
        return hid
    it = _parse_enum(item_type, BOMItemType, "item_type")
    if isinstance(it, dict):
        return it
    if parent_item_id:
        piid = _parse_uuid(parent_item_id, "parent_item_id")
        if isinstance(piid, dict):
            return piid
    else:
        piid = None

    # Verify BOM header exists and belongs to tenant
    header = await db.get(BOMHeader, hid)
    if not header or header.tenant_id != tenant.id:
        return {"error": f"BOM header {bom_header_id} not found"}

    # Get next sort_order
    stmt = select(BOMItem).where(BOMItem.bom_header_id == header.id)
    existing = (await db.execute(stmt)).scalars().all()
    max_sort = max((i.sort_order for i in existing), default=-1)

    item = BOMItem(
        tenant_id=tenant.id,
        bom_header_id=header.id,
        part_number=part_number,
        part_name=part_name,
        description=description,
        quantity=Decimal(str(quantity)),
        unit_of_measure=unit_of_measure,
        unit_cost=Decimal(str(unit_cost)) if unit_cost is not None else None,
        item_type=it,
        selection_condition=selection_condition,
        parent_item_id=piid,
        sort_order=max_sort + 1,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return {
        "id": str(item.id),
        "part_number": item.part_number,
        "part_name": item.part_name,
        "quantity": float(item.quantity),
        "has_condition": selection_condition is not None,
    }


async def config_create_bom_items_batch(
    bom_header_id: str,
    items: list[dict],
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Batch-create BOM items."""
    from app.db.models.bom import BOMHeader, BOMItem, BOMItemType

    hid = _parse_uuid(bom_header_id, "bom_header_id")
    if isinstance(hid, dict):
        return hid

    header = await db.get(BOMHeader, hid)
    if not header or header.tenant_id != tenant.id:
        return {"error": f"BOM header {bom_header_id} not found"}

    # Get next sort_order
    stmt = select(BOMItem).where(BOMItem.bom_header_id == header.id)
    existing = (await db.execute(stmt)).scalars().all()
    max_sort = max((i.sort_order for i in existing), default=-1)

    created = []
    try:
        for i, item_data in enumerate(items):
            piid = None
            if item_data.get("parent_item_id"):
                piid = _parse_uuid(item_data["parent_item_id"], f"items[{i}].parent_item_id")
                if isinstance(piid, dict):
                    await db.rollback()
                    return piid
            item = BOMItem(
                tenant_id=tenant.id,
                bom_header_id=header.id,
                part_number=item_data["part_number"],
                part_name=item_data["part_name"],
                description=item_data.get("description", ""),
                quantity=Decimal(str(item_data.get("quantity", 1.0))),
                unit_of_measure=item_data.get("unit_of_measure", "EA"),
                unit_cost=Decimal(str(item_data["unit_cost"])) if item_data.get("unit_cost") is not None else None,
                item_type=BOMItemType(item_data.get("item_type", "component")),
                selection_condition=item_data.get("selection_condition"),
                parent_item_id=piid,
                sort_order=max_sort + 1 + i,
            )
            db.add(item)
            created.append({"part_number": item.part_number, "part_name": item.part_name})

        await emit_audit_event(db, action=AuditAction.CREATE, resource_type="bom_items_batch", resource_id=str(header.id), tenant_id=tenant.id, changes={"source": "agent_tool", "count": len(created)})
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("config_bom_items_batch_failed", bom_id=bom_header_id, error=str(exc)[:200])
        return {"error": f"Batch BOM creation failed at item {len(created)}: {str(exc)[:200]}"}

    logger.info("config_bom_items_batch", bom_id=bom_header_id, count=len(created))
    return {"bom_header_id": bom_header_id, "items_created": len(created), "items": created}


async def config_resolve_bom(
    session_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Resolve a configured BOM from a configuration session."""
    from app.apps.cpq.engine.bom_resolver import BOMResolver

    sid = _parse_uuid(session_id, "session_id")
    if isinstance(sid, dict):
        return sid

    resolver = BOMResolver(db)

    try:
        result = await resolver.resolve(
            session_id=sid,
            tenant_id=tenant.id,
        )
        return {
            "total_components": result.get("total_components", 0),
            "total_cost": float(result.get("total_cost", 0)),
            "resolved_items": result.get("resolved_items", [])[:50],  # Cap for context size
        }
    except Exception as exc:
        return {"error": f"BOM resolution failed: {exc}"}


# ── Variant Table Tools ───────────────────────────────────────────────


async def config_create_variant_table(
    product_id: str,
    name: str,
    columns: list[dict],
    rows: list[dict],
    input_columns: list[str],
    output_columns: list[str],
    description: str = "",
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a variant table for tabular constraint lookups."""
    from app.db.models.product import VariantTable

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    table = VariantTable(
        tenant_id=tenant.id,
        product_id=pid,
        name=name,
        description=description,
        columns=columns,
        rows=rows,
        input_columns=input_columns,
        output_columns=output_columns,
    )
    db.add(table)
    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="variant_table", resource_id=str(table.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(table)

    logger.info("config_variant_table_created", table_id=str(table.id), name=name, rows=len(rows))
    return {
        "id": str(table.id),
        "name": table.name,
        "row_count": len(rows),
        "input_columns": input_columns,
        "output_columns": output_columns,
    }


async def config_import_variant_table(
    product_id: str,
    name: str,
    table_data: dict,
    input_columns: list[str],
    output_columns: list[str],
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a variant table from extracted table data (headers + rows)."""
    headers = table_data.get("headers", [])
    raw_rows = table_data.get("rows", [])

    # Convert rows from list-of-lists to list-of-dicts
    columns = [{"name": h, "type": "string"} for h in headers]
    rows = []
    for row in raw_rows:
        row_dict = {}
        for i, cell in enumerate(row):
            if i < len(headers):
                row_dict[headers[i]] = str(cell)
        rows.append(row_dict)

    return await config_create_variant_table(
        product_id=product_id,
        name=name,
        columns=columns,
        rows=rows,
        input_columns=input_columns,
        output_columns=output_columns,
        tenant=tenant,
        db=db,
    )


# ── Pricing Tools ─────────────────────────────────────────────────────


async def config_create_pricing_rule(
    product_id: str,
    name: str,
    rule_type: str,
    expression: dict,
    priority: int = 10,
    currency: str = "EUR",
    description: str = "",
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a pricing rule."""
    from app.db.models.configurator import PricingRule, PricingRuleType

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid
    rt = _parse_enum(rule_type, PricingRuleType, "rule_type")
    if isinstance(rt, dict):
        return rt

    rule = PricingRule(
        tenant_id=tenant.id,
        product_id=pid,
        name=name,
        description=description,
        rule_type=rt,
        expression=expression,
        priority=priority,
        currency=currency,
        is_active=True,
    )
    db.add(rule)
    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="pricing_rule", resource_id=str(rule.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(rule)

    return {"id": str(rule.id), "name": rule.name, "rule_type": rule.rule_type.value}


async def config_simulate_pricing(
    product_id: str,
    selections: dict[str, str],
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Simulate pricing for a set of selections."""
    from app.apps.cpq.engine.engine import ConfiguratorEngine

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    engine = ConfiguratorEngine(db)

    try:
        result = await engine.calculate_price(
            product_id=pid,
            tenant_id=tenant.id,
            selections=selections,
        )
        return result
    except Exception as exc:
        return {"error": f"Pricing simulation failed: {exc}"}


# ── Version Snapshot ──────────────────────────────────────────────────


async def config_create_version_snapshot(
    product_id: str,
    label: str = "",
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a version snapshot of the product's configuration model."""
    from app.apps.cpq.engine.snapshot import SnapshotBuilder

    builder = SnapshotBuilder(db)
    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    try:
        version = await builder.create_snapshot(
            product_id=pid,
            tenant_id=tenant.id,
            label=label or None,
        )
        return {
            "version_id": str(version.get("id", "")),
            "version_number": version.get("version_number", 0),
            "label": version.get("label", ""),
        }
    except Exception as exc:
        return {"error": f"Snapshot creation failed: {exc}"}


# ── Data Source Tools ─────────────────────────────────────────────────


async def config_extract_document(
    data_source_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Extract structured content from a data source."""
    from app.db.models.datasource import DataSource, DataSourceStatus

    ds_id = _parse_uuid(data_source_id, "data_source_id")
    if isinstance(ds_id, dict):
        return ds_id
    stmt = select(DataSource).where(
        DataSource.id == ds_id,
        DataSource.tenant_id == tenant.id,
        DataSource.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    ds = result.scalar_one_or_none()
    if not ds:
        return {"error": f"Data source {data_source_id} not found"}

    # Return cached extraction if available
    if ds.extraction_result:
        return ds.extraction_result

    # Trigger extraction
    if ds.file_key:
        from app.docprocessor.processor import DocumentProcessor

        processor = DocumentProcessor()
        extraction = await processor.process(ds.file_key, tenant.id)

        # Cache the result
        ds.extraction_result = extraction.to_dict()
        ds.status = DataSourceStatus.READY
        ds.chunk_count = extraction.table_count + extraction.section_count
        await db.commit()

        return extraction.to_dict()
    elif ds.url:
        from app.docprocessor.processor import DocumentProcessor

        processor = DocumentProcessor()
        extraction = await processor.process_url(ds.url, tenant.id)

        ds.extraction_result = extraction.to_dict()
        ds.status = DataSourceStatus.READY
        await db.commit()

        return extraction.to_dict()

    return {"error": "Data source has no file or URL to extract"}


async def config_search_datasources(
    query: str,
    limit: int = 10,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Search across tenant data sources using chunk content."""
    from app.db.models.datasource import DataSource, DataSourceChunk

    from app.core.query_utils import escape_like

    # Text-based search (semantic search requires embeddings which may not be available)
    escaped_query = escape_like(query)
    stmt = (
        select(DataSourceChunk)
        .join(DataSource, DataSourceChunk.data_source_id == DataSource.id)
        .where(
            DataSourceChunk.tenant_id == tenant.id,
            DataSource.tenant_id == tenant.id,
            DataSource.deleted_at.is_(None),
            DataSourceChunk.content.ilike(f"%{escaped_query}%"),
        )
        .limit(min(limit, 50))
    )
    result = await db.execute(stmt)
    chunks = result.scalars().all()

    return {
        "query": query,
        "results": [
            {
                "chunk_id": str(c.id),
                "data_source_id": str(c.data_source_id),
                "content": c.content[:2000],
                "section_title": c.section_title,
                "chunk_index": c.chunk_index,
            }
            for c in chunks
        ],
        "count": len(chunks),
    }


# ── Update / Delete Tools ────────────────────────────────────────────


async def config_update_product(
    product_id: str,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    sku_prefix: str | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Update an existing product."""
    from app.db.models.product import Product, ProductStatus

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    stmt = select(Product).where(Product.id == pid, Product.tenant_id == tenant.id, Product.deleted_at.is_(None))
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        return {"error": f"Product {product_id} not found"}

    if name is not None:
        product.name = name
    if description is not None:
        product.description = description
    if sku_prefix is not None:
        product.sku_prefix = sku_prefix
    if status is not None:
        s = _parse_enum(status, ProductStatus, "status")
        if isinstance(s, dict):
            return s
        product.status = s

    await emit_audit_event(db, action=AuditAction.UPDATE, resource_type="product", resource_id=str(product.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(product)
    return {"id": str(product.id), "name": product.name, "status": product.status.value}


async def config_delete_product(
    product_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Soft-delete a product."""
    from datetime import UTC, datetime

    from app.db.models.product import Product

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    stmt = select(Product).where(Product.id == pid, Product.tenant_id == tenant.id, Product.deleted_at.is_(None))
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if not product:
        return {"error": f"Product {product_id} not found"}

    product.deleted_at = datetime.now(UTC)
    await emit_audit_event(db, action=AuditAction.DELETE, resource_type="product", resource_id=str(product.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    return {"deleted": True, "id": product_id}


async def config_update_constraint_rule(
    rule_id: str,
    name: str | None = None,
    expression: dict | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Update an existing constraint rule."""
    from app.db.models.product import ConstraintRule

    rid = _parse_uuid(rule_id, "rule_id")
    if isinstance(rid, dict):
        return rid

    stmt = select(ConstraintRule).where(ConstraintRule.id == rid, ConstraintRule.tenant_id == tenant.id, ConstraintRule.deleted_at.is_(None))
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        return {"error": f"Constraint rule {rule_id} not found"}

    if name is not None:
        rule.name = name
    if expression is not None:
        rule.expression = expression
    if priority is not None:
        rule.priority = priority
    if is_active is not None:
        rule.is_active = is_active

    await emit_audit_event(db, action=AuditAction.UPDATE, resource_type="constraint_rule", resource_id=str(rule.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(rule)
    return {"id": str(rule.id), "name": rule.name, "priority": rule.priority, "is_active": rule.is_active}


async def config_delete_constraint_rule(
    rule_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Soft-delete a constraint rule."""
    from datetime import UTC, datetime

    from app.db.models.product import ConstraintRule

    rid = _parse_uuid(rule_id, "rule_id")
    if isinstance(rid, dict):
        return rid

    stmt = select(ConstraintRule).where(ConstraintRule.id == rid, ConstraintRule.tenant_id == tenant.id, ConstraintRule.deleted_at.is_(None))
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        return {"error": f"Constraint rule {rule_id} not found"}

    rule.deleted_at = datetime.now(UTC)
    await emit_audit_event(db, action=AuditAction.DELETE, resource_type="constraint_rule", resource_id=str(rule.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    return {"deleted": True, "id": rule_id}


async def config_update_pricing_rule(
    rule_id: str,
    name: str | None = None,
    expression: dict | None = None,
    priority: int | None = None,
    is_active: bool | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Update an existing pricing rule."""
    from app.db.models.configurator import PricingRule

    rid = _parse_uuid(rule_id, "rule_id")
    if isinstance(rid, dict):
        return rid

    stmt = select(PricingRule).where(PricingRule.id == rid, PricingRule.tenant_id == tenant.id, PricingRule.deleted_at.is_(None))
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        return {"error": f"Pricing rule {rule_id} not found"}

    if name is not None:
        rule.name = name
    if expression is not None:
        rule.expression = expression
    if priority is not None:
        rule.priority = priority
    if is_active is not None:
        rule.is_active = is_active

    await emit_audit_event(db, action=AuditAction.UPDATE, resource_type="pricing_rule", resource_id=str(rule.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(rule)
    return {"id": str(rule.id), "name": rule.name, "is_active": rule.is_active}


async def config_delete_pricing_rule(
    rule_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Soft-delete a pricing rule."""
    from datetime import UTC, datetime

    from app.db.models.configurator import PricingRule

    rid = _parse_uuid(rule_id, "rule_id")
    if isinstance(rid, dict):
        return rid

    stmt = select(PricingRule).where(PricingRule.id == rid, PricingRule.tenant_id == tenant.id, PricingRule.deleted_at.is_(None))
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if not rule:
        return {"error": f"Pricing rule {rule_id} not found"}

    rule.deleted_at = datetime.now(UTC)
    await emit_audit_event(db, action=AuditAction.DELETE, resource_type="pricing_rule", resource_id=str(rule.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    return {"deleted": True, "id": rule_id}


async def config_list_variant_tables(
    product_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """List variant tables for a product."""
    from app.db.models.product import VariantTable

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid

    stmt = select(VariantTable).where(
        VariantTable.product_id == pid,
        VariantTable.tenant_id == tenant.id,
        VariantTable.deleted_at.is_(None),
    ).order_by(VariantTable.created_at.desc())
    result = await db.execute(stmt)
    tables = result.scalars().all()
    return {
        "variant_tables": [
            {"id": str(t.id), "name": t.name, "row_count": len(t.rows or []), "input_columns": t.input_columns, "output_columns": t.output_columns}
            for t in tables
        ],
        "count": len(tables),
    }


# ── Product Family Tools ─────────────────────────────────────────────


async def config_create_product_family(
    name: str,
    slug: str,
    description: str = "",
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a product family."""
    from app.db.models.product import ProductFamily

    family = ProductFamily(
        tenant_id=tenant.id,
        name=name,
        slug=slug,
        description=description,
    )
    db.add(family)
    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="product_family", resource_id=str(family.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(family)
    return {"id": str(family.id), "name": family.name, "slug": family.slug}


async def config_list_product_families(
    limit: int = 50,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """List product families."""
    from app.db.models.product import ProductFamily

    limit = _clamp_limit(limit)
    stmt = select(ProductFamily).where(
        ProductFamily.tenant_id == tenant.id,
        ProductFamily.deleted_at.is_(None),
    ).order_by(ProductFamily.name).limit(limit)
    result = await db.execute(stmt)
    families = result.scalars().all()
    return {
        "families": [{"id": str(f.id), "name": f.name, "slug": f.slug} for f in families],
        "count": len(families),
    }


# ── Characteristic Group Tools ───────────────────────────────────────


async def config_create_characteristic_group(
    name: str,
    description: str = "",
    display_order: int = 0,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a characteristic group for organizing characteristics."""
    from app.db.models.product import CharacteristicGroup

    group = CharacteristicGroup(
        tenant_id=tenant.id,
        name=name,
        description=description,
        display_order=display_order,
    )
    db.add(group)
    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="characteristic_group", resource_id=str(group.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(group)
    return {"id": str(group.id), "name": group.name, "display_order": group.display_order}


async def config_list_characteristic_groups(
    limit: int = 50,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """List characteristic groups."""
    from app.db.models.product import CharacteristicGroup

    limit = _clamp_limit(limit)
    stmt = select(CharacteristicGroup).where(
        CharacteristicGroup.tenant_id == tenant.id,
        CharacteristicGroup.deleted_at.is_(None),
    ).order_by(CharacteristicGroup.display_order).limit(limit)
    result = await db.execute(stmt)
    groups = result.scalars().all()
    return {
        "groups": [{"id": str(g.id), "name": g.name, "display_order": g.display_order} for g in groups],
        "count": len(groups),
    }


# ── Configuration Session Tools ──────────────────────────────────────


async def config_create_session(
    product_id: str,
    product_version_id: str | None = None,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Create a new configuration session for a product."""
    from app.db.models.configurator import ConfigurationSession

    pid = _parse_uuid(product_id, "product_id")
    if isinstance(pid, dict):
        return pid
    vid = None
    if product_version_id:
        vid = _parse_uuid(product_version_id, "product_version_id")
        if isinstance(vid, dict):
            return vid

    session = ConfigurationSession(
        tenant_id=tenant.id,
        product_id=pid,
        product_version_id=vid,
    )
    db.add(session)
    await emit_audit_event(db, action=AuditAction.CREATE, resource_type="configuration_session", resource_id=str(session.id), tenant_id=tenant.id, changes={"source": "agent_tool"})
    await db.commit()
    await db.refresh(session)
    return {"id": str(session.id), "product_id": product_id, "status": session.status.value if hasattr(session.status, "value") else str(session.status)}


async def config_get_session(
    session_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Get a configuration session with its selections."""
    from app.db.models.configurator import ConfigurationSession

    sid = _parse_uuid(session_id, "session_id")
    if isinstance(sid, dict):
        return sid

    stmt = select(ConfigurationSession).where(
        ConfigurationSession.id == sid,
        ConfigurationSession.tenant_id == tenant.id,
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        return {"error": f"Configuration session {session_id} not found"}

    return {
        "id": str(session.id),
        "product_id": str(session.product_id),
        "status": session.status.value if hasattr(session.status, "value") else str(session.status),
        "selections": session.selections or {},
        "is_valid": session.is_valid if hasattr(session, "is_valid") else None,
    }


async def config_make_selection(
    session_id: str,
    characteristic_slug: str,
    value: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Make a selection in a configuration session."""
    from app.apps.cpq.engine.engine import ConfiguratorEngine

    sid = _parse_uuid(session_id, "session_id")
    if isinstance(sid, dict):
        return sid

    engine = ConfiguratorEngine(db)
    try:
        result = await engine.make_selection(
            session_id=sid,
            tenant_id=tenant.id,
            characteristic_slug=characteristic_slug,
            value=value,
        )
        return result
    except Exception as exc:
        return {"error": f"Selection failed: {str(exc)[:200]}"}


async def config_list_sessions(
    product_id: str | None = None,
    limit: int = 20,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """List configuration sessions."""
    from app.db.models.configurator import ConfigurationSession

    limit = _clamp_limit(limit)
    stmt = select(ConfigurationSession).where(ConfigurationSession.tenant_id == tenant.id)
    if product_id:
        pid = _parse_uuid(product_id, "product_id")
        if isinstance(pid, dict):
            return pid
        stmt = stmt.where(ConfigurationSession.product_id == pid)
    stmt = stmt.order_by(ConfigurationSession.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    sessions = result.scalars().all()
    return {
        "sessions": [
            {
                "id": str(s.id),
                "product_id": str(s.product_id),
                "status": s.status.value if hasattr(s.status, "value") else str(s.status),
            }
            for s in sessions
        ],
        "count": len(sessions),
    }


# ── MCP tool registration ─────────────────────────────────────────────


def register_cpq_tools(mcp, get_context) -> None:
    """Register all CPQ tools on the shared FastMCP server.

    Called by CPQPlugin.get_mcp_tools() during startup.  Each tool is a
    thin wrapper that handles auth, scope checking, and JSON serialization,
    then delegates to the corresponding handler function above.
    """
    import json as _json

    from app.mcp.auth import check_scopes

    def _log(tool: str, tid: str) -> None:
        from app.config import settings as _s
        if _s.MCP_LOG_TOOL_CALLS:
            logger.info("mcp_tool_call", tool=tool, tenant_id=tid)

    @mcp.tool(tags={"configurator"})
    async def mcp_config_create_product(name: str, slug: str, description: str = "", sku_prefix: str = "", family_id: str = "") -> str:
        """Create a configurable product. Returns the product ID, name, and slug."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await config_create_product(name=name, slug=slug, description=description, sku_prefix=sku_prefix, family_id=family_id or None, tenant=tenant, db=db)
            _log("config_create_product", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_list_products(status: str = "", limit: int = 50) -> str:
        """List products for the tenant. Optionally filter by status (draft, active, deprecated, archived)."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:read")
            result = await config_list_products(status=status or None, limit=limit, tenant=tenant, db=db)
            _log("config_list_products", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_get_product(product_id: str) -> str:
        """Get product with characteristics, constraints, and BOMs."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:read")
            result = await config_get_product(product_id=product_id, tenant=tenant, db=db)
            _log("config_get_product", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_create_characteristic(
        name: str, slug: str, char_type: str, group_id: str = "", values: str = "[]",
        numeric_min: float | None = None, numeric_max: float | None = None,
        numeric_step: float | None = None, unit: str = "", is_required: bool = False,
        is_multi_select: bool = False, default_value: str = "", description: str = "",
    ) -> str:
        """Create a characteristic (configurable option). char_type: enum, numeric, boolean, text."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            parsed_values = _json.loads(values) if values and values != "[]" else []
            result = await config_create_characteristic(
                name=name, slug=slug, char_type=char_type, group_id=group_id or None,
                values=parsed_values, numeric_min=numeric_min, numeric_max=numeric_max,
                numeric_step=numeric_step, unit=unit or None, is_required=is_required,
                is_multi_select=is_multi_select, default_value=default_value or None,
                description=description, tenant=tenant, db=db,
            )
            _log("config_create_characteristic", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_assign_characteristic(product_id: str, characteristic_id: str, display_order: int = 0, is_required: bool | None = None, default_value: str = "") -> str:
        """Assign a characteristic to a product with optional overrides."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await config_assign_characteristic(product_id=product_id, characteristic_id=characteristic_id, display_order=display_order, is_required=is_required, default_value=default_value or None, tenant=tenant, db=db)
            _log("config_assign_characteristic", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_list_characteristics(product_id: str = "") -> str:
        """List characteristics, optionally filtered by product assignment."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:read")
            result = await config_list_characteristics(product_id=product_id or None, tenant=tenant, db=db)
            _log("config_list_characteristics", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_create_constraint_rule(
        product_id: str, name: str, constraint_type: str, expression: str,
        group_id: str = "", description: str = "", priority: int = 10,
    ) -> str:
        """Create a constraint rule with JSONB AST expression."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await config_create_constraint_rule(product_id=product_id, name=name, constraint_type=constraint_type, expression=_json.loads(expression), group_id=group_id or None, description=description, priority=priority, tenant=tenant, db=db)
            _log("config_create_constraint_rule", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_validate_constraints(product_id: str) -> str:
        """Validate constraints for a product: detect cycles, dead values, coverage gaps."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:read")
            result = await config_validate_constraints(product_id=product_id, tenant=tenant, db=db)
            _log("config_validate_constraints", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_simulate_configuration(product_id: str, selections: str) -> str:
        """Simulate constraint propagation. selections: JSON string of {char_slug: value} pairs."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:read")
            result = await config_simulate_configuration(product_id=product_id, selections=_json.loads(selections), tenant=tenant, db=db)
            _log("config_simulate_configuration", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_create_bom_header(product_id: str, name: str, description: str = "", bom_type: str = "manufacturing", is_primary: bool = True) -> str:
        """Create a 150%% super BOM header for a product."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await config_create_bom_header(product_id=product_id, name=name, description=description, bom_type=bom_type, is_primary=is_primary, tenant=tenant, db=db)
            _log("config_create_bom_header", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_create_bom_item(
        bom_header_id: str, part_number: str, part_name: str, quantity: float = 1.0,
        selection_condition: str = "", item_type: str = "component",
        parent_item_id: str = "", description: str = "", unit_of_measure: str = "EA",
        unit_cost: float | None = None,
    ) -> str:
        """Add a BOM item with optional selection_condition AST."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            parsed_condition = _json.loads(selection_condition) if selection_condition else None
            result = await config_create_bom_item(
                bom_header_id=bom_header_id, part_number=part_number, part_name=part_name,
                quantity=quantity, selection_condition=parsed_condition, item_type=item_type,
                parent_item_id=parent_item_id or None, description=description,
                unit_of_measure=unit_of_measure, unit_cost=unit_cost, tenant=tenant, db=db,
            )
            _log("config_create_bom_item", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_create_bom_items_batch(bom_header_id: str, items: str) -> str:
        """Batch-create BOM items."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await config_create_bom_items_batch(bom_header_id=bom_header_id, items=_json.loads(items), tenant=tenant, db=db)
            _log("config_create_bom_items_batch", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_create_variant_table(
        product_id: str, name: str, columns: str, rows: str,
        input_columns: str, output_columns: str, description: str = "",
    ) -> str:
        """Create a variant table for tabular constraint lookups."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await config_create_variant_table(
                product_id=product_id, name=name, columns=_json.loads(columns),
                rows=_json.loads(rows), input_columns=_json.loads(input_columns),
                output_columns=_json.loads(output_columns), description=description,
                tenant=tenant, db=db,
            )
            _log("config_create_variant_table", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_create_pricing_rule(
        product_id: str, name: str, rule_type: str, expression: str,
        priority: int = 10, currency: str = "EUR", description: str = "",
    ) -> str:
        """Create a pricing rule."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await config_create_pricing_rule(
                product_id=product_id, name=name, rule_type=rule_type,
                expression=_json.loads(expression), priority=priority,
                currency=currency, description=description, tenant=tenant, db=db,
            )
            _log("config_create_pricing_rule", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()

    @mcp.tool(tags={"configurator"})
    async def mcp_config_create_version_snapshot(product_id: str, label: str = "") -> str:
        """Create a version snapshot of a product's configuration model for rollback."""
        api_key, tenant, db = await get_context()
        try:
            check_scopes(api_key, "configurator:write")
            result = await config_create_version_snapshot(product_id=product_id, label=label, tenant=tenant, db=db)
            _log("config_create_version_snapshot", str(tenant.id))
            return _json.dumps(result)
        finally:
            await db.close()
