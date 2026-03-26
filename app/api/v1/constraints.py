"""Constraint rules, groups, and variant table CRUD endpoints."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.configurator.engine import ConfiguratorEngine, NumericInterval
from app.core.audit import AuditAction, emit_audit_event
from app.api.schemas_configurator import (
    ConstraintAnalysisRequest,
    ConstraintAnalysisResponse,
    ConstraintGroupCreate,
    ConstraintGroupResponse,
    ConstraintGroupUpdate,
    ConstraintImpactRequest,
    ConstraintImpactResponse,
    ConstraintRuleCreate,
    ConstraintRuleResponse,
    ConstraintRuleUpdate,
    ConstraintSimulationRequest,
    ConstraintSimulationResponse,
    ConstraintValidateRequest,
    ConstraintValidateResponse,
    CharacteristicImpactResponse,
    CoverageGapResponse,
    CycleInfoResponse,
    DeadValueResponse,
    VariantTableCreate,
    VariantTableResponse,
    VariantTableUpdate,
)
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.db.base import optimistic_version_bump
from app.db.models import ConstraintGroup, ConstraintRule, ConstraintType, Product, Tenant, VariantTable

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/constraints", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()

VALID_OPERATORS = {"eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "between", "and", "or", "not"}


def _validate_operators_recursive(node: dict, errors: list[str]) -> None:
    """Recursively validate all 'op' values in a condition tree."""
    if not isinstance(node, dict):
        return
    op = node.get("op")
    if op and op not in VALID_OPERATORS:
        errors.append(f"Unknown operator '{op}'")
    for sub in node.get("conditions", []):
        _validate_operators_recursive(sub, errors)
    if isinstance(node.get("condition"), dict):
        _validate_operators_recursive(node["condition"], errors)
    if isinstance(node.get("if"), dict):
        _validate_operators_recursive(node["if"], errors)
    if isinstance(node.get("then"), dict):
        _validate_operators_recursive(node["then"], errors)


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

    # Validate all operators in the expression tree
    _validate_operators_recursive(expression, errors)
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
    # Validate product exists
    product_result = await db.execute(
        tenant_query(select(Product), tenant).where(
            Product.id == body.product_id, Product.deleted_at.is_(None)
        )
    )
    if not product_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")

    group = ConstraintGroup(
        tenant_id=tenant.id,
        product_id=body.product_id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
    )
    db.add(group)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="constraint_group",
        resource_id=str(group.id), tenant_id=tenant.id,
    )
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
    # Validate product exists
    product_result = await db.execute(
        tenant_query(select(Product), tenant).where(
            Product.id == body.product_id, Product.deleted_at.is_(None)
        )
    )
    if not product_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")

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
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="constraint_rule",
        resource_id=str(rule.id), tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(rule)
    ConfiguratorEngine.invalidate_product_cache(body.product_id, tenant.id)
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
    await optimistic_version_bump(db, rule)
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="constraint_rule",
        resource_id=str(rule.id), tenant_id=tenant.id, changes=update_data,
    )
    await db.commit()
    await db.refresh(rule)
    ConfiguratorEngine.invalidate_product_cache(rule.product_id, tenant.id)
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
    await emit_audit_event(
        db, action=AuditAction.DELETE, resource_type="constraint_rule",
        resource_id=str(rule.id), tenant_id=tenant.id,
    )
    await db.commit()
    ConfiguratorEngine.invalidate_product_cache(rule.product_id, tenant.id)


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
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="variant_table",
        resource_id=str(table.id), tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(table)
    ConfiguratorEngine.invalidate_product_cache(body.product_id, tenant.id)
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
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(table, field, value)
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="variant_table",
        resource_id=str(table.id), tenant_id=tenant.id, changes=changes,
    )
    await db.commit()
    await db.refresh(table)
    ConfiguratorEngine.invalidate_product_cache(table.product_id, tenant.id)
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
    product_id = table.product_id
    await emit_audit_event(
        db, action=AuditAction.DELETE, resource_type="variant_table",
        resource_id=str(table.id), tenant_id=tenant.id,
    )
    await db.delete(table)
    await db.commit()
    ConfiguratorEngine.invalidate_product_cache(product_id, tenant.id)


# ── Constraint Analysis ─────────────────────────────────


@router.post(
    "/analysis",
    response_model=ConstraintAnalysisResponse,
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def analyze_constraints(
    body: ConstraintAnalysisRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Analyze constraint network for cycles, dead values, coverage gaps, and satisfiability."""
    from app.configurator.analyzer import ConstraintAnalyzer

    engine = ConfiguratorEngine()
    char_map = await engine._load_characteristics(db, body.product_id, tenant.id)
    constraints = await engine._load_constraints(db, body.product_id, tenant.id)
    variant_tables = await engine._load_variant_tables(db, body.product_id, tenant.id)

    analyzer = ConstraintAnalyzer()
    result = analyzer.analyze(char_map, constraints, variant_tables)

    return ConstraintAnalysisResponse(
        cycles=[CycleInfoResponse(path=c.path, involved_rules=c.involved_rules) for c in result.cycles],
        dead_values=[DeadValueResponse(
            characteristic=d.characteristic, value=d.value,
            reason=d.reason, excluding_rules=d.excluding_rules,
        ) for d in result.dead_values],
        coverage_gaps=[CoverageGapResponse(
            characteristic=g.characteristic, is_required=g.is_required,
            has_default=g.has_default, reachable_via_constraints=g.reachable_via_constraints,
            gap_description=g.gap_description,
        ) for g in result.coverage_gaps],
        is_satisfiable=result.is_satisfiable,
        satisfiability_note=result.satisfiability_note,
        analysis_duration_ms=result.analysis_duration_ms,
    )


# ── Constraint Simulation ───────────────────────────────


@router.post(
    "/rules/simulate",
    response_model=ConstraintSimulationResponse,
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def simulate_constraints(
    body: ConstraintSimulationRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Simulate constraint propagation with hypothetical selections (no DB writes)."""
    engine = ConfiguratorEngine()
    char_map = await engine._load_characteristics(db, body.product_id, tenant.id)
    constraints = await engine._load_constraints(db, body.product_id, tenant.id)
    variant_tables = await engine._load_variant_tables(db, body.product_id, tenant.id)

    # Validate selections
    for slug in body.selections:
        if slug not in char_map:
            raise HTTPException(status_code=422, detail=f"Unknown characteristic: {slug}")

    domains = engine._build_initial_domains(char_map)
    result = engine._propagate(
        domains, body.selections, constraints, variant_tables, set(body.selections.keys())
    )

    is_valid = len(result.contradictions) == 0
    is_complete = engine._check_completeness(char_map, body.selections, result.auto_set)

    return ConstraintSimulationResponse(
        available_domains=engine._serialize_domains(result.domains),
        auto_set_values=result.auto_set,
        excluded_values=result.excluded,
        contradictions=result.contradictions,
        conflict_explanations=[
            {
                "characteristic": ce.characteristic,
                "trace": [
                    {
                        "rule_id": s.rule_id,
                        "rule_name": s.rule_name,
                        "constraint_type": s.constraint_type,
                        "target_char": s.target_char,
                        "removed_values": s.removed_values,
                    }
                    for s in ce.trace
                ],
                "contributing_selections": ce.contributing_selections,
            }
            for ce in result.conflict_explanations
        ],
        is_valid=is_valid,
        is_complete=is_complete,
    )


@router.post(
    "/impact-analysis",
    response_model=ConstraintImpactResponse,
    dependencies=[Depends(RequireScopes("products:read"))],
)
async def analyze_impact(
    body: ConstraintImpactRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Analyze the impact of a single constraint rule by comparing propagation with/without it."""
    engine = ConfiguratorEngine()
    char_map = await engine._load_characteristics(db, body.product_id, tenant.id)
    constraints = await engine._load_constraints(db, body.product_id, tenant.id)
    variant_tables = await engine._load_variant_tables(db, body.product_id, tenant.id)

    selections = body.selections
    changed = set(selections.keys()) if selections else set(char_map.keys())

    # Determine which rule to analyze
    target_rule_id = str(body.rule_id) if body.rule_id else None

    if body.rule_expression and body.rule_constraint_type:
        # Create an inline simulated rule
        from dataclasses import dataclass as _dc, field as _field
        from app.db.models import ConstraintType as _CT

        @_dc
        class _SimRule:
            id: str = "simulated"
            name: str = "simulated-rule"
            is_active: bool = True
            effective_from: object = None
            effective_to: object = None
            constraint_type: object = _CT(body.rule_constraint_type)
            expression: dict = _field(default_factory=dict)

        sim_rule = _SimRule(expression=body.rule_expression)
        constraints_with = constraints + [sim_rule]
        constraints_without = constraints
    elif target_rule_id:
        constraints_without = [c for c in constraints if str(c.id) != target_rule_id]
        constraints_with = constraints
    else:
        raise HTTPException(status_code=422, detail="Provide either rule_id or rule_expression+rule_constraint_type")

    # Run propagation without the rule
    domains_without = engine._build_initial_domains(char_map)
    result_without = engine._propagate(domains_without, selections, constraints_without, variant_tables, changed)

    # Run propagation with the rule
    domains_with = engine._build_initial_domains(char_map)
    result_with = engine._propagate(domains_with, selections, constraints_with, variant_tables, changed)

    # Diff
    affected: list[CharacteristicImpactResponse] = []
    total_pruned = 0
    serialized_before = engine._serialize_domains(result_without.domains)
    serialized_after = engine._serialize_domains(result_with.domains)

    for slug in char_map:
        dom_before = result_without.domains.get(slug, set())
        dom_after = result_with.domains.get(slug, set())
        if dom_before == dom_after:
            continue

        pruned: list[str] = []
        if isinstance(dom_before, set) and isinstance(dom_after, set):
            pruned = sorted(dom_before - dom_after)
        elif isinstance(dom_before, NumericInterval) and isinstance(dom_after, NumericInterval):
            if dom_before != dom_after:
                pruned = [f"narrowed from [{dom_before.min},{dom_before.max}] to [{dom_after.min},{dom_after.max}]"]

        total_pruned += len(pruned)
        affected.append(CharacteristicImpactResponse(
            characteristic=slug,
            values_pruned=pruned,
            domain_before=serialized_before.get(slug),
            domain_after=serialized_after.get(slug),
            was_auto_set=slug in result_with.auto_set and slug not in result_without.auto_set,
        ))

    new_contradictions = [c for c in result_with.contradictions if c not in result_without.contradictions]
    new_auto_sets = {k: v for k, v in result_with.auto_set.items() if k not in result_without.auto_set}

    return ConstraintImpactResponse(
        affected_characteristics=affected,
        new_contradictions=new_contradictions,
        new_auto_sets=new_auto_sets,
        total_values_pruned=total_pruned,
    )
