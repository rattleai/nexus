"""Constraint network snapshot compiler for ProductVersion.

Builds a comprehensive, pre-compiled snapshot of the product's configuration
model at a point in time. Used by the engine to skip DB loads + index building
when a session is pinned to a specific product version.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Characteristic,
    CharacteristicAssignment,
    ConstraintRule,
    Product,
    VariantTable,
)

logger = structlog.stdlib.get_logger()

SNAPSHOT_SCHEMA_VERSION = 1


async def compile_snapshot(
    db: AsyncSession,
    product_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """Build a comprehensive pre-compiled snapshot of product configuration data.

    Includes characteristics, constraints, variant tables, dependency index,
    and initial domains. Used to avoid DB round-trips during propagation.
    """
    # Load product
    product_result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = product_result.scalar_one()

    # Load characteristics with values
    assignment_result = await db.execute(
        select(CharacteristicAssignment)
        .where(
            CharacteristicAssignment.product_id == product_id,
            CharacteristicAssignment.tenant_id == tenant_id,
        )
        .options(
            selectinload(CharacteristicAssignment.characteristic)
            .selectinload(Characteristic.values)
        )
    )

    characteristics: dict[str, dict] = {}
    initial_domains: dict[str, list[str] | dict] = {}
    for assignment in assignment_result.scalars().all():
        char = assignment.characteristic
        if char.deleted_at is not None:
            continue
        char_data: dict = {
            "id": str(char.id),
            "name": char.name,
            "slug": char.slug,
            "char_type": char.char_type.value,
            "is_required": char.is_required,
            "is_multi_select": char.is_multi_select,
            "numeric_min": char.numeric_min,
            "numeric_max": char.numeric_max,
            "numeric_step": char.numeric_step,
            "unit": char.unit,
            "default_value": char.default_value,
            "min_select": assignment.min_select,
            "max_select": assignment.max_select,
        }
        if char.char_type.value == "enum":
            values = [v.value for v in char.values]
            char_data["values"] = values
            initial_domains[char.slug] = values
        elif char.char_type.value == "boolean":
            char_data["values"] = ["true", "false"]
            initial_domains[char.slug] = ["true", "false"]
        elif char.char_type.value == "numeric":
            initial_domains[char.slug] = {
                "type": "numeric",
                "min": char.numeric_min,
                "max": char.numeric_max,
                "step": char.numeric_step,
            }
        else:
            char_data["values"] = ["__any__"]
            initial_domains[char.slug] = ["__any__"]
        characteristics[char.slug] = char_data

    # Load constraints
    from app.apps.cpq.engine.engine import ConfiguratorEngine

    engine = ConfiguratorEngine()
    constraint_result = await db.execute(
        select(ConstraintRule)
        .where(
            ConstraintRule.product_id == product_id,
            ConstraintRule.tenant_id == tenant_id,
            ConstraintRule.deleted_at.is_(None),
        )
        .order_by(ConstraintRule.priority.desc())
    )

    dependency_index: dict[str, list[str]] = defaultdict(list)
    constraints_data: list[dict] = []

    for c in constraint_result.scalars().all():
        referenced = engine._extract_referenced_chars(c.expression)
        constraint_id = str(c.id)
        constraint_data = {
            "id": constraint_id,
            "name": c.name,
            "constraint_type": c.constraint_type.value,
            "expression": c.expression,
            "priority": c.priority,
            "is_active": c.is_active,
            "effective_from": c.effective_from.isoformat() if c.effective_from else None,
            "effective_to": c.effective_to.isoformat() if c.effective_to else None,
            "referenced_chars": sorted(referenced),
        }
        constraints_data.append(constraint_data)
        for char_slug in referenced:
            dependency_index[char_slug].append(constraint_id)

    # Load variant tables
    vtable_result = await db.execute(
        select(VariantTable).where(
            VariantTable.product_id == product_id,
            VariantTable.tenant_id == tenant_id,
        )
    )

    variant_tables: dict[str, dict] = {}
    for vt in vtable_result.scalars().all():
        variant_tables[str(vt.id)] = {
            "id": str(vt.id),
            "name": vt.name,
            "input_columns": vt.input_columns,
            "output_columns": vt.output_columns,
            "rows": vt.rows,
        }

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "product_id": str(product_id),
        "product_name": product.name,
        "compiled_at": datetime.now(UTC).isoformat(),
        "characteristics": characteristics,
        "constraints": constraints_data,
        "variant_tables": variant_tables,
        "dependency_index": dict(dependency_index),
        "initial_domains": initial_domains,
    }
