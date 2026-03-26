"""MCP tools for product configuration domain operations.

These tools enable AI agents to create and manage configurable products,
characteristics, constraint rules, BOMs, variant tables, and pricing rules.
Each handler wraps the same service-layer logic used by the REST API endpoints.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = structlog.stdlib.get_logger()


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

    product = Product(
        tenant_id=tenant.id,
        name=name,
        slug=slug,
        description=description or "",
        sku_prefix=sku_prefix or "",
        family_id=uuid.UUID(family_id) if family_id else None,
        status=ProductStatus.DRAFT,
    )
    db.add(product)
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

    stmt = select(Product).where(
        Product.tenant_id == tenant.id,
        Product.deleted_at.is_(None),
    )
    if status:
        stmt = stmt.where(Product.status == ProductStatus(status))
    stmt = stmt.order_by(Product.created_at.desc()).limit(min(limit, 100))

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

    pid = uuid.UUID(product_id)

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
    from app.db.models.product import Characteristic, CharType, CharacteristicValue

    char = Characteristic(
        tenant_id=tenant.id,
        name=name,
        slug=slug,
        description=description,
        char_type=CharType(char_type),
        group_id=uuid.UUID(group_id) if group_id else None,
        numeric_min=Decimal(str(numeric_min)) if numeric_min is not None else None,
        numeric_max=Decimal(str(numeric_max)) if numeric_max is not None else None,
        numeric_step=Decimal(str(numeric_step)) if numeric_step is not None else None,
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

    char_id = uuid.UUID(characteristic_id)
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

    assignment = CharacteristicAssignment(
        tenant_id=tenant.id,
        product_id=uuid.UUID(product_id),
        characteristic_id=uuid.UUID(characteristic_id),
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
        # List characteristics assigned to this product
        stmt = (
            select(CharacteristicAssignment)
            .options(
                selectinload(CharacteristicAssignment.characteristic)
                .selectinload(Characteristic.values)
            )
            .where(
                CharacteristicAssignment.product_id == uuid.UUID(product_id),
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

    group = ConstraintGroup(
        tenant_id=tenant.id,
        product_id=uuid.UUID(product_id),
        name=name,
        description=description,
    )
    db.add(group)
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

    rule = ConstraintRule(
        tenant_id=tenant.id,
        product_id=uuid.UUID(product_id),
        name=name,
        description=description,
        constraint_type=ConstraintType(constraint_type),
        expression=expression,
        group_id=uuid.UUID(group_id) if group_id else None,
        priority=priority,
        is_active=True,
    )
    db.add(rule)
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
    from app.configurator.analyzer import ConstraintAnalyzer

    analyzer = ConstraintAnalyzer(db)
    pid = uuid.UUID(product_id)

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
    from app.configurator.engine import ConfiguratorEngine

    engine = ConfiguratorEngine(db)
    pid = uuid.UUID(product_id)

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
    from app.configurator.analyzer import ConstraintAnalyzer

    analyzer = ConstraintAnalyzer(db)
    pid = uuid.UUID(product_id)

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

    bom = BOMHeader(
        tenant_id=tenant.id,
        product_id=uuid.UUID(product_id),
        name=name,
        description=description,
        bom_type=bom_type,
        is_primary=is_primary,
    )
    db.add(bom)
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

    # Verify BOM header exists and belongs to tenant
    header = await db.get(BOMHeader, uuid.UUID(bom_header_id))
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
        item_type=BOMItemType(item_type),
        selection_condition=selection_condition,
        parent_item_id=uuid.UUID(parent_item_id) if parent_item_id else None,
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

    header = await db.get(BOMHeader, uuid.UUID(bom_header_id))
    if not header or header.tenant_id != tenant.id:
        return {"error": f"BOM header {bom_header_id} not found"}

    # Get next sort_order
    stmt = select(BOMItem).where(BOMItem.bom_header_id == header.id)
    existing = (await db.execute(stmt)).scalars().all()
    max_sort = max((i.sort_order for i in existing), default=-1)

    created = []
    for i, item_data in enumerate(items):
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
            parent_item_id=uuid.UUID(item_data["parent_item_id"]) if item_data.get("parent_item_id") else None,
            sort_order=max_sort + 1 + i,
        )
        db.add(item)
        created.append({"part_number": item.part_number, "part_name": item.part_name})

    await db.commit()

    logger.info("config_bom_items_batch", bom_id=bom_header_id, count=len(created))
    return {"bom_header_id": bom_header_id, "items_created": len(created), "items": created}


async def config_resolve_bom(
    session_id: str,
    *,
    tenant: Any,
    db: AsyncSession,
) -> dict:
    """Resolve a configured BOM from a configuration session."""
    from app.configurator.bom_resolver import BOMResolver

    resolver = BOMResolver(db)

    try:
        result = await resolver.resolve(
            session_id=uuid.UUID(session_id),
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

    table = VariantTable(
        tenant_id=tenant.id,
        product_id=uuid.UUID(product_id),
        name=name,
        description=description,
        columns=columns,
        rows=rows,
        input_columns=input_columns,
        output_columns=output_columns,
    )
    db.add(table)
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

    rule = PricingRule(
        tenant_id=tenant.id,
        product_id=uuid.UUID(product_id),
        name=name,
        description=description,
        rule_type=PricingRuleType(rule_type),
        expression=expression,
        priority=priority,
        currency=currency,
        is_active=True,
    )
    db.add(rule)
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
    from app.configurator.engine import ConfiguratorEngine

    engine = ConfiguratorEngine(db)

    try:
        result = await engine.calculate_price(
            product_id=uuid.UUID(product_id),
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
    from app.configurator.snapshot import SnapshotBuilder

    builder = SnapshotBuilder(db)
    pid = uuid.UUID(product_id)

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

    ds_id = uuid.UUID(data_source_id)
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

    # Text-based search (semantic search requires embeddings which may not be available)
    stmt = (
        select(DataSourceChunk)
        .join(DataSource, DataSourceChunk.data_source_id == DataSource.id)
        .where(
            DataSourceChunk.tenant_id == tenant.id,
            DataSource.deleted_at.is_(None),
            DataSourceChunk.content.ilike(f"%{query}%"),
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
