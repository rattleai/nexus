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
from app.apps.cpq.api.schemas_configurator import (
    BOMComparisonPart,
    BOMComparisonRequest,
    BOMComparisonResponse,
    BOMComparisonSession,
    BulkActionRequest,
    BulkActionResponse,
    BulkActionResultItem,
    ConfigurationPricingResponse,
    ConfigurationSelectionRequest,
    ConfigurationSessionCreate,
    ConfigurationSessionResponse,
    ConfigurationTemplateCreate,
    ConfigurationTemplateResponse,
    ConfiguredBOMResponse,
    ConflictExplanationResponse,
    ConflictStepResponse,
    PartFrequencyItem,
    PartFrequencyResponse,
    PricingRuleCreate,
    PricingRuleResponse,
    PricingRuleUpdate,
    PricingSimulateRequest,
    SelectionResultResponse,
)
from app.apps.cpq.engine.bom_resolver import BOMResolver
from app.apps.cpq.engine.engine import ConfiguratorEngine
from app.apps.cpq.engine.validator import ConfigurationValidator
from app.apps.cpq.events import (
    BOMResolved,
    ConfigurationCompleted,
    ConfigurationLocked,
    ConfigurationSelectionMade,
    ConfigurationStarted,
    PricingResolved,
)
from app.apps.cpq.models.configurator import (
    ConfigurationPricing,
    ConfigurationSession,
    ConfigurationStatus,
    ConfigurationTemplate,
    ConfiguredBOM,
    PricingRule,
    PricingRuleType,
)
from app.apps.cpq.models.product import Product
from app.core.audit import AuditAction, emit_audit_event
from app.core.events import emit
from app.core.pagination import CursorPage, paginate
from app.core.tenant import tenant_query
from app.db.base import optimistic_version_bump
from app.db.models import Tenant
from app.db.session import set_tenant_context

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
        tenant_query(select(Product), tenant).where(Product.id == body.product_id, Product.deleted_at.is_(None))
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
    await emit_audit_event(
        db,
        action=AuditAction.CREATE,
        resource_type="configuration_session",
        resource_id=str(session.id),
        tenant_id=tenant.id,
    )

    # If created from template, apply template selections
    if body.template_id:
        await db.flush()  # ensure session.id is assigned
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
                    logger.warning("template_selection_skipped", template_id=str(template.id), entry=sel)
            if skipped:
                logger.info(
                    "template_selections_summary", applied=len(pairs), skipped=skipped, template_id=str(template.id)
                )
            if pairs:
                await _engine.apply_selections_batch(db, session.id, pairs)

    await db.commit()

    # Re-set RLS context after commit, then re-query with eager load
    await set_tenant_context(db, str(tenant.id))
    result = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == session.id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session = result.scalar_one()

    await emit(
        ConfigurationStarted(
            session_id=str(session.id),
            product_id=str(body.product_id),
            tenant_id=str(tenant.id),
        )
    )
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
    search: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    has_bom: bool | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    stmt = tenant_query(select(ConfigurationSession), tenant).options(selectinload(ConfigurationSession.selections))
    if product_id:
        stmt = stmt.where(ConfigurationSession.product_id == product_id)
    if status:
        stmt = stmt.where(ConfigurationSession.status == ConfigurationStatus(status))
    if search:
        stmt = stmt.where(ConfigurationSession.name.ilike(f"%{search}%"))
    if created_after:
        stmt = stmt.where(ConfigurationSession.created_at >= created_after)
    if created_before:
        stmt = stmt.where(ConfigurationSession.created_at <= created_before)
    if has_bom is not None:
        bom_exists = (
            select(ConfiguredBOM.id)
            .where(ConfiguredBOM.session_id == ConfigurationSession.id)
            .correlate(ConfigurationSession)
            .exists()
        )
        stmt = stmt.where(bom_exists) if has_bom else stmt.where(~bom_exists)
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
    from app.apps.cpq.models.product import Characteristic

    char_result = await db.execute(
        select(Characteristic).where(Characteristic.id == body.characteristic_id, Characteristic.deleted_at.is_(None))
    )
    char = char_result.scalar_one_or_none()
    if not char:
        raise HTTPException(status_code=404, detail="Characteristic not found")

    result = await _engine.apply_selection(db, session_id, char.slug, body.value)

    if result.validation_errors and result.validation_errors[0].error_type in ("not_found", "locked"):
        raise HTTPException(status_code=400, detail=result.validation_errors[0].message)

    # Re-set RLS context (engine commit clears SET LOCAL)
    await set_tenant_context(db, str(tenant.id))

    # Reload session for response
    session = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session_obj = session.scalar_one()

    await emit(
        ConfigurationSelectionMade(
            session_id=str(session_id),
            characteristic_slug=char.slug,
            value=body.value,
            tenant_id=str(tenant.id),
        )
    )
    if session_obj.status == ConfigurationStatus.COMPLETE:
        await emit(
            ConfigurationCompleted(
                session_id=str(session_id),
                product_id=str(session_obj.product_id),
                tenant_id=str(tenant.id),
            )
        )

    return SelectionResultResponse(
        session=ConfigurationSessionResponse.model_validate(session_obj),
        auto_set_values=result.auto_set_values,
        excluded_values=result.excluded_values,
        conflict_explanations=[
            ConflictExplanationResponse(
                characteristic=ce.characteristic,
                trace=[
                    ConflictStepResponse(
                        rule_id=s.rule_id,
                        rule_name=s.rule_name,
                        constraint_type=s.constraint_type,
                        target_char=s.target_char,
                        removed_values=s.removed_values,
                        triggered_by=s.triggered_by,
                    )
                    for s in ce.trace
                ],
                contributing_selections=ce.contributing_selections,
            )
            for ce in result.conflict_explanations
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

    # Re-set RLS context (engine commit clears SET LOCAL)
    await set_tenant_context(db, str(tenant.id))

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
                trace=[
                    ConflictStepResponse(
                        rule_id=s.rule_id,
                        rule_name=s.rule_name,
                        constraint_type=s.constraint_type,
                        target_char=s.target_char,
                        removed_values=s.removed_values,
                        triggered_by=s.triggered_by,
                    )
                    for s in ce.trace
                ],
                contributing_selections=ce.contributing_selections,
            )
            for ce in result.conflict_explanations
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

    # Re-set RLS context after commit, then re-query with eager load
    await set_tenant_context(db, str(tenant.id))
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

    await emit(
        BOMResolved(
            session_id=str(session_id),
            configured_bom_id=str(configured_bom.id),
            total_components=configured_bom.total_components,
            total_cost=str(configured_bom.total_cost) if configured_bom.total_cost else "0",
            tenant_id=str(tenant.id),
        )
    )

    # Emit pricing event if pricing was resolved
    pricing_result = await db.execute(select(ConfigurationPricing).where(ConfigurationPricing.session_id == session_id))
    pricing = pricing_result.scalar_one_or_none()
    if pricing:
        await emit(
            PricingResolved(
                session_id=str(session_id),
                final_price=str(pricing.final_price),
                margin_percentage=str(pricing.margin_percentage),
                is_profitable=pricing.is_profitable,
                tenant_id=str(tenant.id),
            )
        )

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
    result = await db.execute(tenant_query(select(ConfiguredBOM), tenant).where(ConfiguredBOM.session_id == session_id))
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
        tenant_query(select(ConfigurationPricing), tenant).where(ConfigurationPricing.session_id == session_id)
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
        db,
        action=AuditAction.UPDATE,
        resource_type="configuration_session",
        resource_id=str(session.id),
        tenant_id=tenant.id,
        changes={"status": "locked"},
    )
    await db.commit()

    # Re-set RLS context after commit, then re-query with eager load
    await set_tenant_context(db, str(tenant.id))
    refreshed = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session = refreshed.scalar_one()

    await emit(
        ConfigurationLocked(
            session_id=str(session_id),
            product_id=str(session.product_id),
            tenant_id=str(tenant.id),
        )
    )
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

    from app.apps.cpq.models.configurator import ConfigurationSelection

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

    # Re-set RLS context after commit, then re-query with eager load
    await set_tenant_context(db, str(tenant.id))
    refreshed = await db.execute(
        select(ConfigurationSession)
        .where(ConfigurationSession.id == clone.id)
        .options(selectinload(ConfigurationSession.selections))
    )
    clone = refreshed.scalar_one()
    return clone


# ── Session Management ───────────────────────────────────


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def delete_session(
    session_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant).where(ConfigurationSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Configuration session not found")

    if session.status == ConfigurationStatus.LOCKED:
        raise HTTPException(status_code=400, detail="Cannot delete a locked configuration")

    # Delete related records first
    from app.apps.cpq.models.configurator import ConfigurationSelection

    await db.execute(select(ConfigurationSelection).where(ConfigurationSelection.session_id == session_id))
    for sel in (
        (await db.execute(select(ConfigurationSelection).where(ConfigurationSelection.session_id == session_id)))
        .scalars()
        .all()
    ):
        await db.delete(sel)

    # Delete resolved BOM if present
    bom_result = await db.execute(select(ConfiguredBOM).where(ConfiguredBOM.session_id == session_id))
    bom = bom_result.scalar_one_or_none()
    if bom:
        await db.delete(bom)

    # Delete pricing if present
    pricing_result = await db.execute(select(ConfigurationPricing).where(ConfigurationPricing.session_id == session_id))
    pricing = pricing_result.scalar_one_or_none()
    if pricing:
        await db.delete(pricing)

    await db.delete(session)
    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="configuration_session",
        resource_id=str(session_id),
        tenant_id=tenant.id,
    )
    await db.commit()


@router.post(
    "/sessions/bulk-action",
    response_model=BulkActionResponse,
    dependencies=[Depends(RequireScopes("configurator:write"))],
)
async def bulk_action(
    body: BulkActionRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    results: list[BulkActionResultItem] = []
    for sid in body.session_ids:
        try:
            result = await db.execute(
                tenant_query(select(ConfigurationSession), tenant)
                .where(ConfigurationSession.id == sid)
                .options(selectinload(ConfigurationSession.selections))
            )
            session = result.scalar_one_or_none()
            if not session:
                results.append(BulkActionResultItem(session_id=sid, success=False, error="Not found"))
                continue

            if body.action == "lock":
                if not session.is_valid or not session.is_complete:
                    results.append(
                        BulkActionResultItem(
                            session_id=sid,
                            success=False,
                            error="Incomplete or invalid",
                        )
                    )
                    continue
                session.status = ConfigurationStatus.LOCKED
                results.append(BulkActionResultItem(session_id=sid, success=True))

            elif body.action == "delete":
                if session.status == ConfigurationStatus.LOCKED:
                    results.append(
                        BulkActionResultItem(
                            session_id=sid,
                            success=False,
                            error="Cannot delete locked session",
                        )
                    )
                    continue
                for sel in session.selections:
                    await db.delete(sel)
                bom = (
                    await db.execute(select(ConfiguredBOM).where(ConfiguredBOM.session_id == sid))
                ).scalar_one_or_none()
                if bom:
                    await db.delete(bom)
                pricing = (
                    await db.execute(select(ConfigurationPricing).where(ConfigurationPricing.session_id == sid))
                ).scalar_one_or_none()
                if pricing:
                    await db.delete(pricing)
                await db.delete(session)
                results.append(BulkActionResultItem(session_id=sid, success=True))

            elif body.action == "resolve_bom":
                try:
                    await _resolver.resolve(db, sid)
                    results.append(BulkActionResultItem(session_id=sid, success=True))
                except ValueError as e:
                    results.append(BulkActionResultItem(session_id=sid, success=False, error=str(e)))

        except Exception as e:
            logger.error("bulk_action_error", session_id=str(sid), error=str(e))
            results.append(BulkActionResultItem(session_id=sid, success=False, error="Internal error"))

    await db.commit()

    succeeded = sum(1 for r in results if r.success)
    return BulkActionResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


# ── BOM Analysis ────────────────────────────────────────


@router.post(
    "/bom/compare",
    response_model=BOMComparisonResponse,
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def compare_boms(
    body: BOMComparisonRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Compare resolved BOMs across 2-5 configuration sessions."""
    sessions_data: list[BOMComparisonSession] = []
    all_bom_parts: list[dict[str, dict]] = []  # per-session: {part_number: {name, qty, cost}}

    for sid in body.session_ids:
        # Load session
        sess_result = await db.execute(
            tenant_query(select(ConfigurationSession), tenant).where(ConfigurationSession.id == sid)
        )
        session = sess_result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {sid} not found")

        # Load product name
        prod_result = await db.execute(select(Product.name).where(Product.id == session.product_id))
        product_name = prod_result.scalar_one_or_none()

        sessions_data.append(
            BOMComparisonSession(
                id=session.id,
                name=session.name,
                product_name=product_name,
            )
        )

        # Load resolved BOM
        bom_result = await db.execute(
            tenant_query(select(ConfiguredBOM), tenant).where(ConfiguredBOM.session_id == sid)
        )
        bom = bom_result.scalar_one_or_none()

        part_map: dict[str, dict] = {}
        if bom and bom.resolved_items:
            for item in bom.resolved_items:
                pn = item.get("part_number", "")
                part_map[pn] = {
                    "part_name": item.get("part_name", ""),
                    "quantity": float(item.get("quantity", 0)),
                    "unit_cost": float(item.get("unit_cost", 0)),
                }
        all_bom_parts.append(part_map)

    # Find common and unique parts
    all_part_numbers = set()
    for pm in all_bom_parts:
        all_part_numbers.update(pm.keys())

    common_parts: list[BOMComparisonPart] = []
    unique_parts: list[BOMComparisonPart] = []

    n = len(body.session_ids)
    for pn in sorted(all_part_numbers):
        present_in = [pm.get(pn) for pm in all_bom_parts]
        present_count = sum(1 for p in present_in if p is not None)

        part_name = next((p["part_name"] for p in present_in if p is not None), "")
        quantities = [p["quantity"] if p else None for p in present_in]
        unit_costs = [p["unit_cost"] if p else None for p in present_in]

        part = BOMComparisonPart(
            part_number=pn,
            part_name=part_name,
            quantities=quantities,
            unit_costs=unit_costs,
        )
        if present_count == n:
            common_parts.append(part)
        else:
            unique_parts.append(part)

    # Cost comparison per session
    cost_comparison = []
    for i, sid in enumerate(body.session_ids):
        total = sum(p["quantity"] * p["unit_cost"] for p in all_bom_parts[i].values())
        cost_comparison.append(
            {
                "session_id": str(sid),
                "total_cost": round(total, 4),
                "total_parts": len(all_bom_parts[i]),
            }
        )

    return BOMComparisonResponse(
        sessions=sessions_data,
        common_parts=common_parts,
        unique_parts=unique_parts,
        cost_comparison=cost_comparison,
    )


@router.get(
    "/bom/part-frequency",
    response_model=PartFrequencyResponse,
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def part_frequency(
    product_id: uuid.UUID | None = None,
    limit: int = Query(default=20, le=100),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Get most frequently used parts across all resolved BOMs."""
    stmt = tenant_query(select(ConfiguredBOM), tenant)
    if product_id:
        stmt = stmt.join(ConfigurationSession, ConfiguredBOM.session_id == ConfigurationSession.id).where(
            ConfigurationSession.product_id == product_id,
        )

    result = await db.execute(stmt)
    boms = list(result.scalars().all())

    total_configs = len(boms)
    part_counts: dict[str, dict] = {}  # {part_number: {name, count}}

    for bom in boms:
        seen_parts = set()
        for item in bom.resolved_items or []:
            pn = item.get("part_number", "")
            if pn and pn not in seen_parts:
                seen_parts.add(pn)
                if pn not in part_counts:
                    part_counts[pn] = {"part_name": item.get("part_name", ""), "count": 0}
                part_counts[pn]["count"] += 1

    # Sort by count descending, limit
    sorted_parts = sorted(part_counts.items(), key=lambda x: x[1]["count"], reverse=True)[:limit]

    items = [
        PartFrequencyItem(
            part_number=pn,
            part_name=data["part_name"],
            usage_count=data["count"],
            percentage=round(data["count"] / total_configs * 100, 1) if total_configs > 0 else 0,
        )
        for pn, data in sorted_parts
    ]

    return PartFrequencyResponse(items=items, total_configurations=total_configs)


@router.get(
    "/sessions/{session_id}/export",
    dependencies=[Depends(RequireScopes("configurator:read"))],
)
async def export_session(
    session_id: uuid.UUID,
    format: str = Query(default="csv", pattern=r"^(csv|json)$"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Export a configuration session's BOM and pricing as CSV or JSON."""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    # Load session
    session_result = await db.execute(
        tenant_query(select(ConfigurationSession), tenant)
        .where(ConfigurationSession.id == session_id)
        .options(selectinload(ConfigurationSession.selections))
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Configuration session not found")

    # Load product name
    prod_result = await db.execute(select(Product.name).where(Product.id == session.product_id))
    product_name = prod_result.scalar_one_or_none() or "Unknown"

    # Load resolved BOM
    bom_result = await db.execute(
        tenant_query(select(ConfiguredBOM), tenant).where(ConfiguredBOM.session_id == session_id)
    )
    bom = bom_result.scalar_one_or_none()

    # Load pricing
    pricing_result = await db.execute(
        tenant_query(select(ConfigurationPricing), tenant).where(ConfigurationPricing.session_id == session_id)
    )
    pricing = pricing_result.scalar_one_or_none()

    if format == "json":
        import json as json_mod

        export_data = {
            "session": {
                "id": str(session.id),
                "name": session.name,
                "product": product_name,
                "status": session.status.value if hasattr(session.status, "value") else str(session.status),
                "created_at": session.created_at.isoformat(),
            },
            "selections": [
                {"characteristic_id": str(s.characteristic_id), "value": s.value, "is_auto_set": s.is_auto_set}
                for s in session.selections
            ],
            "bom": {
                "resolved_items": bom.resolved_items if bom else [],
                "total_components": bom.total_components if bom else 0,
                "total_cost": float(bom.total_cost) if bom and bom.total_cost else None,
            },
            "pricing": {
                "base_price": float(pricing.base_price) if pricing else None,
                "total_adjustments": float(pricing.total_adjustments) if pricing else None,
                "final_price": float(pricing.final_price) if pricing else None,
                "margin_percentage": float(pricing.margin_percentage) if pricing else None,
                "is_profitable": pricing.is_profitable if pricing else None,
            },
        }
        content = json_mod.dumps(export_data, indent=2)
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=config-{session_id}.json"},
        )

    # CSV format
    output = io.StringIO()
    writer = csv.writer(output)

    # Header info
    writer.writerow(["Configuration Export"])
    writer.writerow(["Session", str(session.id)])
    writer.writerow(["Name", session.name or ""])
    writer.writerow(["Product", product_name])
    writer.writerow(["Status", session.status.value if hasattr(session.status, "value") else str(session.status)])
    writer.writerow(["Created", session.created_at.isoformat()])
    writer.writerow([])

    # BOM section
    writer.writerow(["Bill of Materials"])
    writer.writerow(["Part Number", "Part Name", "Type", "Quantity", "UOM", "Unit Cost", "Extended Cost"])
    if bom and bom.resolved_items:
        for item in bom.resolved_items:
            qty = float(item.get("quantity", 0))
            cost = float(item.get("unit_cost", 0))
            writer.writerow(
                [
                    item.get("part_number", ""),
                    item.get("part_name", ""),
                    item.get("item_type", ""),
                    qty,
                    item.get("unit", "EA"),
                    f"{cost:.2f}",
                    f"{qty * cost:.2f}",
                ]
            )
        writer.writerow([])
        writer.writerow(["Total Components", bom.total_components])
        writer.writerow(["Total Cost", f"{float(bom.total_cost):.2f}" if bom.total_cost else "N/A"])
    writer.writerow([])

    # Pricing section
    writer.writerow(["Pricing"])
    if pricing:
        writer.writerow(["Base Price", f"{float(pricing.base_price):.2f}"])
        writer.writerow(["Adjustments", f"{float(pricing.total_adjustments):.2f}"])
        writer.writerow(["Final Price", f"{float(pricing.final_price):.2f}"])
        writer.writerow(["Margin %", f"{float(pricing.margin_percentage):.1f}%"])
        writer.writerow(["Profitable", "Yes" if pricing.is_profitable else "No"])
    else:
        writer.writerow(["No pricing resolved"])

    content = output.getvalue()
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=config-{session_id}.csv"},
    )


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
        db,
        action=AuditAction.CREATE,
        resource_type="configuration_template",
        resource_id=str(template.id),
        tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(template)
    await db.commit()
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
    stmt = tenant_query(select(ConfigurationTemplate), tenant).where(ConfigurationTemplate.product_id == product_id)
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
                raise HTTPException(
                    status_code=422, detail=f"Tier {i}: overlaps with previous tier (min={t_min}, prev_max={prev_max})"
                )
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
        db,
        action=AuditAction.CREATE,
        resource_type="pricing_rule",
        resource_id=str(rule.id),
        tenant_id=tenant.id,
    )
    await db.flush()
    await db.refresh(rule)
    await db.commit()
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
    stmt = tenant_query(select(PricingRule), tenant).where(
        PricingRule.product_id == product_id, PricingRule.deleted_at.is_(None)
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
        tenant_query(select(PricingRule), tenant).where(PricingRule.id == rule_id, PricingRule.deleted_at.is_(None))
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
        tenant_query(select(PricingRule), tenant).where(PricingRule.id == rule_id, PricingRule.deleted_at.is_(None))
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(rule, field, value)
    await optimistic_version_bump(db, rule)
    await emit_audit_event(
        db,
        action=AuditAction.UPDATE,
        resource_type="pricing_rule",
        resource_id=str(rule.id),
        tenant_id=tenant.id,
        changes=changes,
    )
    await db.flush()
    await db.refresh(rule)
    await db.commit()
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
        tenant_query(select(PricingRule), tenant).where(PricingRule.id == rule_id, PricingRule.deleted_at.is_(None))
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    rule.deleted_at = datetime.now(UTC)
    await emit_audit_event(
        db,
        action=AuditAction.DELETE,
        resource_type="pricing_rule",
        resource_id=str(rule.id),
        tenant_id=tenant.id,
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
        tenant_query(select(PricingRule), tenant)
        .where(
            PricingRule.product_id == body.product_id,
            PricingRule.deleted_at.is_(None),
            PricingRule.is_active.is_(True),
        )
        .order_by(PricingRule.priority.desc())
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
