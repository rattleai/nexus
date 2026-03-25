"""Configuration session management, live configuration, and BOM resolution endpoints."""

import uuid

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
    ConfiguredBOMResponse,
    PricingRuleCreate,
    PricingRuleResponse,
    PricingRuleUpdate,
    PricingSimulateRequest,
    SelectionResultResponse,
)
from app.configurator.bom_resolver import BOMResolver
from app.configurator.engine import ConfiguratorEngine
from app.configurator.validator import ConfigurationValidator
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
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
        available_domains={k: sorted(v) for k, v in domains.items()},
    )
    db.add(session)
    await db.commit()
    await db.refresh(session, attribute_names=["selections"])

    # If created from template, apply template selections
    if body.template_id:
        template_result = await db.execute(
            select(ConfigurationTemplate).where(
                ConfigurationTemplate.id == body.template_id,
                ConfigurationTemplate.tenant_id == tenant.id,
            )
        )
        template = template_result.scalar_one_or_none()
        if template:
            for sel in template.selections:
                slug = sel.get("characteristic_slug") or sel.get("slug")
                value = sel.get("value")
                if slug and value:
                    await _engine.apply_selection(db, session.id, slug, value)
            await db.refresh(session, attribute_names=["selections"])

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

    return SelectionResultResponse(
        session=ConfigurationSessionResponse.model_validate(session_obj),
        auto_set_values=result.auto_set_values,
        excluded_values=result.excluded_values,
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
    session.available_domains = {k: sorted(v) for k, v in domains.items()}
    session.is_valid = False
    session.is_complete = False
    session.validation_errors = None
    session.status = ConfigurationStatus.IN_PROGRESS

    await db.commit()
    await db.refresh(session, attribute_names=["selections"])
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
    await db.commit()
    await db.refresh(session, attribute_names=["selections"])
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
    await db.refresh(clone, attribute_names=["selections"])
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
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    rule.version += 1
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
    from datetime import UTC, datetime

    result = await db.execute(
        tenant_query(select(PricingRule), tenant).where(
            PricingRule.id == rule_id, PricingRule.deleted_at.is_(None)
        )
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    rule.deleted_at = datetime.now(UTC)
    await db.commit()
