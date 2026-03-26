"""Configuration session management, live configuration, and BOM resolution endpoints."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import RequireScopes, get_current_tenant, get_db
from app.api.rate_limit import ApiKeyRateLimiter
from app.api.schemas_configurator import (
    ConfigurationPricingResponse,
    ConfigurationSessionCreate,
    ConfigurationSessionResponse,
    ConfigurationSelectionRequest,
    ConfigurationTemplateCreate,
    ConfigurationTemplateResponse,
    ConflictExplanationResponse,
    ConflictStepResponse,
    ConfiguredBOMResponse,
    PricingRuleCreate,
    PricingRuleResponse,
    PricingRuleUpdate,
    PricingSimulateRequest,
    SelectionResultResponse,
)
from app.configurator.bom_resolver import BOMResolver
from app.configurator.engine import ConfiguratorEngine
from app.configurator.events import (
    BOMResolved,
    ConfigurationCompleted,
    ConfigurationLocked,
    ConfigurationSelectionMade,
    ConfigurationStarted,
    PricingResolved,
)
from app.configurator.validator import ConfigurationValidator
from app.core.audit import AuditAction, emit_audit_event
from app.core.events import emit
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.db.base import optimistic_version_bump
from app.db.models import (
    ConfigurationPricing,
    ConfigurationSession,
    ConfigurationStatus,
    ConfigurationTemplate,
    ConfiguredBOM,
    PricingRule,
    PricingRuleType,
    Product,
    Tenant,
)

_api_key_rate_limit = ApiKeyRateLimiter()
router = APIRouter(prefix="/configurator", dependencies=[Depends(_api_key_rate_limit)])
logger = structlog.stdlib.get_logger()

_engine = ConfiguratorEngine()
_validator = ConfigurationValidator()
_resolver = BOMResolver()


# ── Sessions ─────────────────────────────────────────────


@router.post(
    "/sessions",
    response_model=ConfigurationSessionResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def create_session(
    body: ConfigurationSessionCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Verify product exists
    product_result = await db.execute(
        tenant_query(select(Product), tenant).where(
            Product.id == body.product_id, Product.deleted_at.is_(None)
        )
    )
    if not product_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")

    # Initialize domains
    domains = await _engine.initialize_domains(db, body.product_id, tenant.id)

    session = ConfigurationSession(
        tenant_id=tenant.id,
        product_id=body.product_id,
        product_version_id=body.product_version_id,
        name=body.name,
        template_id=body.template_id,
        external_reference=body.external_reference,
        available_domains=domains,
    )
    db.add(session)
    await db.flush()  # flush to assign the id before audit log references it
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="configuration_session",
        resource_id=str(session.id), tenant_id=tenant.id,
    )
    await db.commit()

    # If created from template, apply template selections
    if body.template_id:
        template_result = await db.execute(
            tenant_query(select(ConfigurationTemplate), tenant).where(
                ConfigurationTemplate.id == body.template_id,
            )
        )
        template = template_result.scalar_one_or_none()
        if template:
            pairs = []
            skipped = 0
            for sel in template.selections:
                slug = sel.get("characteristic_slug") or sel.get("slug")
                value = sel.get("value")
                if slug and value:
                    pairs.append((slug, value))
                else:
                    skipped += 1
                    logger.warning("template_selection_skipped",
                                   template_id=str(template.id), entry=sel)
            if skipped:
                logger.info("template_selections_summary",
                            applied=len(pairs), skipped=skipped,
                            template_id=str(template.id))
            if pairs:
                await _engine.apply_selections_batch(db, session.id, pairs)
                await db.commit()

    # Re-query with selections eagerly loaded — more robust than db.refresh()
    result = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == session.id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session = result.scalar_one()

    await emit(ConfigurationStarted(
        session_id=str(session.id), product_id=str(body.product_id), tenant_id=str(tenant.id),
    ))
    return session


@router.get(
    "/sessions",
    response_model=CursorPage[ConfigurationSessionResponse],
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def list_sessions(
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    product_id: uuid.UUID | None = None,
    status: str | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        tenant_query(select(ConfigurationSession), tenant)
        .options(selectinload(ConfigurationSession.selections))
    )
    if product_id:
        stmt = stmt.where(ConfigurationSession.product_id == product_id)
    if status:
        stmt = stmt.where(ConfigurationSession.status == ConfigurationStatus(status))
    return await paginate(db, stmt, ConfigurationSession.created_at, limit=limit, cursor=cursor, descending=True)


@router.get(
    "/sessions/{session_id}",
    response_model=ConfigurationSessionResponse,
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def get_session(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Configuration session not found")
    return session


@router.post(
    "/sessions/{session_id}/select",
    response_model=SelectionResultResponse,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def make_selection(
    session_id: uuid.UUID,
    body: ConfigurationSelectionRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Get session to verify tenant
    session_result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant).where(ConfigurationSession.id == session_id)
    )
    if not session_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Configuration session not found")

    # Resolve characteristic slug from ID
    from app.db.models import Characteristic
    char_result = await db.execute(
        select(Characteristic).where(Characteristic.id == body.characteristic_id, Characteristic.deleted_at.is_(None))
    )
    char = char_result.scalar_one_or_none()
    if not char:
        raise HTTPException(status_code=404, detail="Characteristic not found")

    result = await _engine.apply_selection(db, session_id, char.slug, body.value)

    if result.validation_errors and result.validation_errors[0].error_type in ("not_found", "locked"):
        raise HTTPException(status_code=400, detail=result.validation_errors[0].message)

    # Reload session for response
    session = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session_obj = session.scalar_one()

    await emit(ConfigurationSelectionMade(
        session_id=str(session_id), characteristic_slug=char.slug,
        value=body.value, tenant_id=str(tenant.id),
    ))
    if session_obj.status == ConfigurationStatus.COMPLETE:
        await emit(ConfigurationCompleted(
            session_id=str(session_id), product_id=str(session_obj.product_id),
            tenant_id=str(tenant.id),
        ))

    return SelectionResultResponse(
        session=ConfigurationSessionResponse.model_validate(session_obj),
        auto_set_values=result.auto_set_values,
        excluded_values=result.excluded_values,
        conflict_explanations=[
            ConflictExplanationResponse(
                characteristic=ce.characteristic,
                trace=[ConflictStepResponse(
                    rule_id=s.rule_id, rule_name=s.rule_name,
                    constraint_type=s.constraint_type, target_char=s.target_char,
                    removed_values=s.removed_values, triggered_by=s.triggered_by,
                ) for s in ce.trace],
                contributing_selections=ce.contributing_selections,
            ) for ce in result.conflict_explanations
        ],
    )


@router.delete(
    "/sessions/{session_id}/select/{characteristic_id}",
    response_model=SelectionResultResponse,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def remove_selection(
    session_id: uuid.UUID,
    characteristic_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    session_result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant).where(ConfigurationSession.id == session_id)
    )
    if not session_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Configuration session not found")

    result = await _engine.remove_selection(db, session_id, characteristic_id)

    session = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session_obj = session.scalar_one()

    return SelectionResultResponse(
        session=ConfigurationSessionResponse.model_validate(session_obj),
        auto_set_values=result.auto_set_values,
        excluded_values=result.excluded_values,
        conflict_explanations=[
            ConflictExplanationResponse(
                characteristic=ce.characteristic,
                trace=[ConflictStepResponse(
                    rule_id=s.rule_id, rule_name=s.rule_name,
                    constraint_type=s.constraint_type, target_char=s.target_char,
                    removed_values=s.removed_values, triggered_by=s.triggered_by,
                ) for s in ce.trace],
                contributing_selections=ce.contributing_selections,
            ) for ce in result.conflict_explanations
        ],
    )


@router.post(
    "/sessions/{session_id}/reset",
    response_model=ConfigurationSessionResponse,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def reset_session(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Configuration session not found")

    # Delete all selections
    for sel in session.selections:
        await db.delete(sel)

    # Re-initialize domains
    domains = await _engine.initialize_domains(db, session.product_id, session.tenant_id)
    session.available_domains = domains
    session.is_valid = False
    session.is_complete = False
    session.validation_errors = None
    session.status = ConfigurationStatus.IN_PROGRESS

    await db.commit()

    # Re-query with selections eagerly loaded
    refreshed = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session = refreshed.scalar_one()
    return session


@router.get(
    "/sessions/{session_id}/validate",
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def validate_session(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    session_result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant).where(ConfigurationSession.id == session_id)
    )
    if not session_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Configuration session not found")

    result = await _validator.validate(db, session_id)
    return {
        "is_valid": result.is_valid,
        "is_complete": result.is_complete,
        "errors": [
            {"characteristic_slug": e.characteristic_slug, "error_type": e.error_type, "message": e.message}
            for e in result.errors
        ],
    }


@router.post(
    "/sessions/{session_id}/resolve-bom",
    response_model=ConfiguredBOMResponse,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def resolve_bom(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    session_result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant).where(ConfigurationSession.id == session_id)
    )
    if not session_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Configuration session not found")

    try:
        configured_bom = await _resolver.resolve(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await emit(BOMResolved(
        session_id=str(session_id), configured_bom_id=str(configured_bom.id),
        total_components=configured_bom.total_components,
        total_cost=str(configured_bom.total_cost) if configured_bom.total_cost else "0",
        tenant_id=str(tenant.id),
    ))

    # Emit pricing event if pricing was resolved
    pricing_result = await db.execute(
        select(ConfigurationPricing).where(ConfigurationPricing.session_id == session_id)
    )
    pricing = pricing_result.scalar_one_or_none()
    if pricing:
        await emit(PricingResolved(
            session_id=str(session_id), final_price=str(pricing.final_price),
            margin_percentage=str(pricing.margin_percentage),
            is_profitable=pricing.is_profitable, tenant_id=str(tenant.id),
        ))

    return configured_bom


@router.get(
    "/sessions/{session_id}/bom",
    response_model=ConfiguredBOMResponse,
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def get_resolved_bom(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConfiguredBOM), tenant).where(ConfiguredBOM.session_id == session_id)
    )
    bom = result.scalar_one_or_none()
    if not bom:
        raise HTTPException(status_code=404, detail="No resolved BOM found for this session")
    return bom


@router.get(
    "/sessions/{session_id}/pricing",
    response_model=ConfigurationPricingResponse,
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def get_pricing(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConfigurationPricing), tenant).where(
            ConfigurationPricing.session_id == session_id
        )
    )
    pricing = result.scalar_one_or_none()
    if not pricing:
        raise HTTPException(status_code=404, detail="No pricing found for this session")
    return pricing


@router.post(
    "/sessions/{session_id}/lock",
    response_model=ConfigurationSessionResponse,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def lock_session(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Configuration session not found")

    if not session.is_valid or not session.is_complete:
        raise HTTPException(status_code=400, detail="Cannot lock an incomplete or invalid configuration")

    session.status = ConfigurationStatus.LOCKED
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="configuration_session",
        resource_id=str(session.id), tenant_id=tenant.id,
        changes={"status": "locked"},
    )
    await db.commit()

    # Re-query with selections eagerly loaded
    refreshed = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session = refreshed.scalar_one()

    await emit(ConfigurationLocked(
        session_id=str(session_id), product_id=str(session.product_id),
        tenant_id=str(tenant.id),
    ))
    return session


@router.post(
    "/sessions/{session_id}/clone",
    response_model=ConfigurationSessionResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def clone_session(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Configuration session not found")

    clone = ConfigurationSession(
        tenant_id=tenant.id,
        product_id=source.product_id,
        product_version_id=source.product_version_id,
        name=f"{source.name or 'Config'} (copy)" if source.name else "Configuration (copy)",
        status=ConfigurationStatus.IN_PROGRESS,
        available_domains=source.available_domains,
    )
    db.add(clone)
    await db.flush()

    from app.db.models import ConfigurationSelection
    for sel in source.selections:
        new_sel = ConfigurationSelection(
            tenant_id=tenant.id,
            session_id=clone.id,
            characteristic_id=sel.characteristic_id,
            value=sel.value,
            is_auto_set=sel.is_auto_set,
            set_by_rule_id=sel.set_by_rule_id,
        )
        db.add(new_sel)

    await db.commit()

    # Re-query with selections eagerly loaded
    refreshed = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == clone.id)
        .options(selectinload(ConfigurationSession.selections))
    )
    clone = refreshed.scalar_one()
    return clone


# ── Templates ────────────────────────────────────────────


@router.post(
    "/templates",
    response_model=ConfigurationTemplateResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def create_template(
    body: ConfigurationTemplateCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    template = ConfigurationTemplate(
        tenant_id=tenant.id,
        product_id=body.product_id,
        name=body.name,
        description=body.description,
        is_partial=body.is_partial,
        is_public=body.is_public,
        selections=body.selections,
    )
    db.add(template)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="configuration_template",
        resource_id=str(template.id), tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(template)
    return template


@router.get(
    "/templates",
    response_model=CursorPage[ConfigurationTemplateResponse],
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def list_templates(
    product_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = tenant_query(select(ConfigurationTemplate), tenant).where(
        ConfigurationTemplate.product_id == product_id
    )
    return await paginate(db, stmt, ConfigurationTemplate.created_at, limit=limit, cursor=cursor, descending=True)


# ── Pricing Rules ────────────────────────────────────────


@router.post(
    "/pricing/rules",
    response_model=PricingRuleResponse,
    status_code=201,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def create_pricing_rule(
    body: PricingRuleCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    # Validate tiered pricing expression
    if body.rule_type == "tiered":
        expr = body.expression or {}
        tiers = expr.get("tiers")
        if not tiers or not isinstance(tiers, list):
            raise HTTPException(status_code=422, detail="Tiered pricing requires a non-empty 'tiers' list")
        tier_model = expr.get("tier_model", "all_units")
        if tier_model not in ("all_units", "marginal"):
            raise HTTPException(status_code=422, detail="tier_model must be 'all_units' or 'marginal'")
        prev_max = None
        for i, tier in enumerate(tiers):
            if "min" not in tier or "price" not in tier:
                raise HTTPException(status_code=422, detail=f"Tier {i}: must have 'min' and 'price'")
            try:
                t_min = float(tier["min"])
                t_price = float(tier["price"])
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail=f"Tier {i}: 'min' and 'price' must be numeric")
            if t_price < 0:
                raise HTTPException(status_code=422, detail=f"Tier {i}: 'price' must be non-negative")
            t_max = tier.get("max")
            if t_max is not None:
                try:
                    t_max = float(t_max)
                except (ValueError, TypeError):
                    raise HTTPException(status_code=422, detail=f"Tier {i}: 'max' must be numeric or null")
                if t_max < t_min:
                    raise HTTPException(status_code=422, detail=f"Tier {i}: 'max' must be >= 'min'")
            if prev_max is not None and t_min <= prev_max:
                raise HTTPException(status_code=422, detail=f"Tier {i}: overlaps with previous tier (min={t_min}, prev_max={prev_max})")
            prev_max = t_max

    rule = PricingRule(
        tenant_id=tenant.id,
        product_id=body.product_id,
        name=body.name,
        description=body.description,
        rule_type=PricingRuleType(body.rule_type),
        expression=body.expression,
        priority=body.priority,
        is_active=body.is_active,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        currency=body.currency,
    )
    db.add(rule)
    await emit_audit_event(
        db, action=AuditAction.CREATE, resource_type="pricing_rule",
        resource_id=str(rule.id), tenant_id=tenant.id,
    )
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get(
    "/pricing/rules",
    response_model=CursorPage[PricingRuleResponse],
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def list_pricing_rules(
    product_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=20, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        tenant_query(select(PricingRule), tenant)
        .where(PricingRule.product_id == product_id, PricingRule.deleted_at.is_(None))
    )
    return await paginate(db, stmt, PricingRule.created_at, limit=limit, cursor=cursor, descending=True)


@router.get(
    "/pricing/rules/{rule_id}",
    response_model=PricingRuleResponse,
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def get_pricing_rule(
    rule_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(PricingRule), tenant).where(
            PricingRule.id == rule_id, PricingRule.deleted_at.is_(None)
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    return rule


@router.put(
    "/pricing/rules/{rule_id}",
    response_model=PricingRuleResponse,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def update_pricing_rule(
    rule_id: uuid.UUID,
    body: PricingRuleUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(PricingRule), tenant).where(
            PricingRule.id == rule_id, PricingRule.deleted_at.is_(None)
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(rule, field, value)
    await optimistic_version_bump(db, rule)
    await emit_audit_event(
        db, action=AuditAction.UPDATE, resource_type="pricing_rule",
        resource_id=str(rule.id), tenant_id=tenant.id, changes=changes,
    )
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete(
    "/pricing/rules/{rule_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def delete_pricing_rule(
    rule_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(PricingRule), tenant).where(
            PricingRule.id == rule_id, PricingRule.deleted_at.is_(None)
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    rule.deleted_at = datetime.now(UTC)
    await emit_audit_event(
        db, action=AuditAction.DELETE, resource_type="pricing_rule",
        resource_id=str(rule.id), tenant_id=tenant.id,
    )
    await db.commit()


# ── Pricing Simulation ───────────────────────────────────


@router.post(
    "/pricing/simulate",
    response_model=ConfigurationPricingResponse,
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def simulate_pricing(
    body: PricingSimulateRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Simulate pricing for a set of selections without creating a session."""
    # Load pricing rules for the product
    rules_result = await db.execute(
        tenant_query(select(PricingRule), tenant).where(
            PricingRule.product_id == body.product_id,
            PricingRule.deleted_at.is_(None),
            PricingRule.is_active.is_(True),
        ).order_by(PricingRule.priority.desc())
    )
    rules = list(rules_result.scalars().all())

    base_price = Decimal("0")
    total_adjustments = Decimal("0")
    breakdown: list[dict] = []
    min_margin_pct = Decimal("0")
    now = datetime.now(UTC)

    for rule in rules:
        if rule.effective_from and now < rule.effective_from:
            continue
        if rule.effective_to and now > rule.effective_to:
            continue

        expr = rule.expression
        rt = rule.rule_type.value

        if rt == "base_price":
            amount = Decimal(str(expr.get("amount", 0)))
            base_price += amount
            breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})
        elif rt == "option_surcharge":
            condition = expr.get("condition", {})
            if _engine._evaluate_condition(condition, body.selections):
                amount = Decimal(str(expr.get("amount", 0)))
                total_adjustments += amount
                breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})
        elif rt == "conditional":
            condition = expr.get("condition", {})
            if _engine._evaluate_condition(condition, body.selections):
                adj_type = expr.get("adjustment_type", "fixed")
                amount = Decimal(str(expr.get("amount", 0)))
                actual = base_price * amount / Decimal("100") if adj_type == "percentage" else amount
                total_adjustments += actual
                breakdown.append({"rule": rule.name, "type": rt, "amount": str(actual)})
        elif rt == "margin":
            min_margin_pct = Decimal(str(expr.get("min_margin_pct", 0)))
        else:
            amount = Decimal(str(expr.get("amount", 0)))
            total_adjustments += amount
            breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})

    final_price = base_price + total_adjustments
    # Cost is unknown in simulation (no BOM resolved), use 0
    total_cost = Decimal("0")
    margin_amount = final_price - total_cost
    margin_pct = (margin_amount / final_price * 100) if final_price > 0 else Decimal("0")

    import uuid as _uuid
    return ConfigurationPricingResponse(
        id=_uuid.uuid4(),
        session_id=_uuid.UUID(int=0),
        currency="EUR",
        base_price=base_price,
        total_adjustments=total_adjustments,
        final_price=final_price,
        total_cost=total_cost,
        margin_amount=margin_amount,
        margin_percentage=margin_pct,
        price_breakdown=breakdown,
        is_profitable=margin_pct >= min_margin_pct,
        resolved_at=now,
    )
