"""Constraint rules, groups, and variant table CRUD endpoints."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.api.schemas_configurator import (
    ConstraintGroupCreate,
    ConstraintGroupResponse,
    ConstraintGroupUpdate,
    ConstraintRuleCreate,
    ConstraintRuleResponse,
    ConstraintRuleUpdate,
    ConstraintValidateRequest,
    ConstraintValidateResponse,
    VariantTableCreate,
    VariantTableResponse,
    VariantTableUpdate,
)
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.db.models import ConstraintGroup, ConstraintRule, ConstraintType, Tenant, VariantTable

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/constraints", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()

VALID_OPERATORS = {"eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "and", "or", "not"}


def _validate_expression(expression: dict, constraint_type: str) -> list[str]:
    """Validate a constraint expression AST. Returns list of errors."""
    errors = []
    expr_type = expression.get("type")
    if expr_type and expr_type != constraint_type:
        errors.append(f"Expression type '{expr_type}' does not match constraint_type '{constraint_type}'")

    if constraint_type in ("requires", "excludes"):
        if "if" not in expression:
            errors.append("'if' clause is required for requires/excludes constraints")
        if "then" not in expression:
            errors.append("'then' clause is required for requires/excludes constraints")
    elif constraint_type == "selection_condition":
        if "target" not in expression:
            errors.append("'target' is required for selection_condition constraints")
        if "condition" not in expression:
            errors.append("'condition' is required for selection_condition constraints")
    elif constraint_type == "table":
        if "table_id" not in expression:
            errors.append("'table_id' is required for table constraints")
    return errors


# ── Constraint Groups ────────────────────────────────────


@router.post(
    "/groups",
    response_model=ConstraintGroupResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def create_constraint_group(
    body: ConstraintGroupCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    group = ConstraintGroup(
        tenant_id=tenant.id,
        product_id=body.product_id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


@router.get(
    "/groups",
    response_model=CursorPage[ConstraintGroupResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_constraint_groups(
    product_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        tenant_query(select(ConstraintGroup), tenant)
        .where(ConstraintGroup.product_id == product_id, ConstraintGroup.deleted_at.is_(None))
    )
    return await paginate(db, stmt, ConstraintGroup.created_at, limit=limit, cursor=cursor, descending=True)


# ── Constraint Rules ─────────────────────────────────────


@router.post(
    "/rules",
    response_model=ConstraintRuleResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def create_constraint_rule(
    body: ConstraintRuleCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    errors = _validate_expression(body.expression, body.constraint_type)
    if errors:
        raise HTTPException(status_code=422, detail=f"Invalid expression: {'; '.join(errors)}")

    rule = ConstraintRule(
        tenant_id=tenant.id,
        product_id=body.product_id,
        group_id=body.group_id,
        name=body.name,
        description=body.description,
        constraint_type=ConstraintType(body.constraint_type),
        expression=body.expression,
        priority=body.priority,
        is_active=body.is_active,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get(
    "/rules",
    response_model=CursorPage[ConstraintRuleResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_constraint_rules(
    product_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    constraint_type: str | None = None,
    group_id: uuid.UUID | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        tenant_query(select(ConstraintRule), tenant)
        .where(ConstraintRule.product_id == product_id, ConstraintRule.deleted_at.is_(None))
    )
    if constraint_type:
        stmt = stmt.where(ConstraintRule.constraint_type == ConstraintType(constraint_type))
    if group_id:
        stmt = stmt.where(ConstraintRule.group_id == group_id)
    return await paginate(db, stmt, ConstraintRule.created_at, limit=limit, cursor=cursor, descending=True)


@router.get(
    "/rules/{rule_id}",
    response_model=ConstraintRuleResponse,
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def get_constraint_rule(
    rule_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConstraintRule), tenant).where(
            ConstraintRule.id == rule_id, ConstraintRule.deleted_at.is_(None)
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Constraint rule not found")
    return rule


@router.put(
    "/rules/{rule_id}",
    response_model=ConstraintRuleResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_constraint_rule(
    rule_id: uuid.UUID,
    body: ConstraintRuleUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConstraintRule), tenant).where(
            ConstraintRule.id == rule_id, ConstraintRule.deleted_at.is_(None)
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Constraint rule not found")

    update_data = body.model_dump(exclude_unset=True)
    if "expression" in update_data:
        errors = _validate_expression(update_data["expression"], rule.constraint_type.value)
        if errors:
            raise HTTPException(status_code=422, detail=f"Invalid expression: {'; '.join(errors)}")

    for field, value in update_data.items():
        setattr(rule, field, value)
    rule.version += 1
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete(
    "/rules/{rule_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def delete_constraint_rule(
    rule_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConstraintRule), tenant).where(
            ConstraintRule.id == rule_id, ConstraintRule.deleted_at.is_(None)
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Constraint rule not found")
    rule.deleted_at = datetime.now(UTC)
    await db.commit()


@router.post(
    "/rules/validate",
    response_model=ConstraintValidateResponse,
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def validate_expression(body: ConstraintValidateRequest):
    errors = _validate_expression(body.expression, body.constraint_type)
    return ConstraintValidateResponse(is_valid=len(errors) == 0, errors=errors)


# ── Variant Tables ───────────────────────────────────────


@router.post(
    "/tables",
    response_model=VariantTableResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def create_variant_table(
    body: VariantTableCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    table = VariantTable(
        tenant_id=tenant.id,
        product_id=body.product_id,
        name=body.name,
        description=body.description,
        columns=body.columns,
        rows=body.rows,
        input_columns=body.input_columns,
        output_columns=body.output_columns,
    )
    db.add(table)
    await db.commit()
    await db.refresh(table)
    return table


@router.get(
    "/tables",
    response_model=CursorPage[VariantTableResponse],
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def list_variant_tables(
    product_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = tenant_query(select(VariantTable), tenant).where(VariantTable.product_id == product_id)
    return await paginate(db, stmt, VariantTable.created_at, limit=limit, cursor=cursor, descending=True)


@router.put(
    "/tables/{table_id}",
    response_model=VariantTableResponse,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def update_variant_table(
    table_id: uuid.UUID,
    body: VariantTableUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(VariantTable), tenant).where(VariantTable.id == table_id)
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Variant table not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(table, field, value)
    await db.commit()
    await db.refresh(table)
    return table


@router.delete(
    "/tables/{table_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("products:write"))],
)
async def delete_variant_table(
    table_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(VariantTable), tenant).where(VariantTable.id == table_id)
    )
    table = result.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Variant table not found")
    await db.delete(table)
    await db.commit()
