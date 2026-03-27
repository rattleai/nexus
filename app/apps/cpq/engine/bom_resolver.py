"""BOM resolution — filters a 150% super BOM to a configured 100% BOM."""

from __future__ import annotations

import ast
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.apps.cpq.engine.engine import ConfiguratorEngine
from app.core.metrics import CONFIGURATOR_BOM_RESOLUTION_DURATION
from app.apps.cpq.models.bom import BOMHeader, BOMItem, BOMItemType
from app.apps.cpq.models.configurator import (
    ConfigurationPricing,
    ConfigurationSession,
    ConfiguredBOM,
    PricingRule,
)

logger = structlog.stdlib.get_logger()


def _safe_decimal(value, default: Decimal = Decimal("0")) -> Decimal:
    """Convert a value to Decimal, returning default on failure."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        logger.warning("invalid_decimal_value", value=value)
        return default


def _bom_eager_load(depth: int = 5):
    """Build chained selectinload for BOM item hierarchy up to given depth."""
    load = selectinload(BOMHeader.items)
    current = load
    for _ in range(depth - 1):
        current = current.selectinload(BOMItem.children)
    return load


@dataclass
class ResolvedItem:
    part_number: str
    part_name: str
    quantity: Decimal
    unit: str
    unit_cost: Decimal | None
    level: int
    parent_part: str | None
    source_bom_item_id: str
    item_type: str
    quantity_expression: dict | None = None


class BOMResolver:
    """Resolves a 150% super BOM to a configured 100% BOM."""

    def __init__(self):
        self._engine = ConfiguratorEngine()

    async def resolve(
        self, db: AsyncSession, session_id: uuid.UUID, max_depth: int = 5
    ) -> ConfiguredBOM:
        """Full BOM resolution pipeline."""
        start = time.monotonic()

        session = await self._engine._load_session(db, session_id)
        if not session:
            raise ValueError("Configuration session not found")

        char_map = await self._engine._load_characteristics(db, session.product_id, session.tenant_id)
        selections = self._engine._build_selections_map(session.selections, char_map)

        # Find primary BOM
        bom_result = await db.execute(
            select(BOMHeader)
            .where(
                BOMHeader.product_id == session.product_id,
                BOMHeader.tenant_id == session.tenant_id,
                BOMHeader.is_primary.is_(True),
                BOMHeader.deleted_at.is_(None),
            )
            .options(_bom_eager_load(max_depth))
        )
        bom_header = bom_result.scalar_one_or_none()
        if not bom_header:
            raise ValueError("No primary BOM found for this product")

        # Filter and resolve items
        resolved = self._filter_items(bom_header.items, selections, level=0)
        resolved = self._flatten_phantoms(resolved)
        resolved = self._resolve_quantities(resolved, selections)

        # Calculate totals
        total_cost = Decimal("0")
        for item in resolved:
            if item.unit_cost is not None:
                total_cost += item.quantity * item.unit_cost

        resolved_items_json = [
            {
                "part_number": r.part_number,
                "part_name": r.part_name,
                "quantity": str(r.quantity),
                "unit": r.unit,
                "unit_cost": str(r.unit_cost) if r.unit_cost else None,
                "level": r.level,
                "parent_part": r.parent_part,
                "source_bom_item_id": r.source_bom_item_id,
                "item_type": r.item_type,
                "quantity_expression": r.quantity_expression,
            }
            for r in resolved
        ]

        duration_ms = int((time.monotonic() - start) * 1000)

        # Delete existing resolved BOM if any (lock row to prevent concurrent race)
        existing = await db.execute(
            select(ConfiguredBOM).where(ConfiguredBOM.session_id == session_id)
            .with_for_update(skip_locked=False)
        )
        existing_bom = existing.scalar_one_or_none()
        if existing_bom:
            await db.delete(existing_bom)
            await db.flush()

        configured_bom = ConfiguredBOM(
            tenant_id=session.tenant_id,
            session_id=session.id,
            bom_header_id=bom_header.id,
            resolved_items=resolved_items_json,
            total_components=len(resolved),
            total_cost=total_cost,
            selection_snapshot=selections,
            resolution_duration_ms=duration_ms,
        )
        db.add(configured_bom)

        # Resolve pricing
        await self._resolve_pricing(db, session, selections, total_cost, resolved_items_json)

        await db.flush()
        await db.refresh(configured_bom)
        await db.commit()
        CONFIGURATOR_BOM_RESOLUTION_DURATION.observe(duration_ms / 1000.0)
        return configured_bom

    def _filter_items(
        self,
        items: list[BOMItem],
        selections: dict[str, str],
        level: int,
    ) -> list[ResolvedItem]:
        """Filter BOM items based on selection conditions."""
        resolved = []
        now = datetime.now(UTC)

        for item in items:
            if item.deleted_at is not None:
                continue

            # Check effectivity
            if item.effective_from and now < item.effective_from:
                continue
            if item.effective_to and now > item.effective_to:
                continue

            # Evaluate selection condition
            if item.selection_condition is not None:
                if not self._engine._evaluate_condition(item.selection_condition, selections):
                    continue

            resolved.append(ResolvedItem(
                part_number=item.part_number,
                part_name=item.part_name,
                quantity=item.quantity,
                unit=item.unit_of_measure,
                unit_cost=item.unit_cost,
                level=level,
                parent_part=None,
                source_bom_item_id=str(item.id),
                item_type=item.item_type.value,
                quantity_expression=item.quantity_expression,
            ))

            # Recurse into children (use inspect to avoid lazy load in async)
            from sqlalchemy import inspect as sa_inspect
            item_state = sa_inspect(item)
            if "children" in item_state.dict and item.children:
                child_items = self._filter_items(item.children, selections, level + 1)
                for child in child_items:
                    child.parent_part = item.part_number
                resolved.extend(child_items)

        return resolved

    def _flatten_phantoms(self, items: list[ResolvedItem]) -> list[ResolvedItem]:
        """Replace phantom items with their children, multiplying quantities."""
        result = []
        phantom_quantities: dict[str, Decimal] = {}

        for item in items:
            if item.item_type == "phantom":
                parent_multiplier = phantom_quantities.get(item.parent_part, Decimal("1"))
                phantom_quantities[item.part_number] = item.quantity * parent_multiplier
                continue

            # If parent is a phantom, multiply quantity
            if item.parent_part in phantom_quantities:
                item.quantity *= phantom_quantities[item.parent_part]
                item.parent_part = None  # Promote to top-level
                item.level = max(0, item.level - 1)

            result.append(item)

        return result

    def _resolve_quantities(
        self, items: list[ResolvedItem], selections: dict[str, str]
    ) -> list[ResolvedItem]:
        """Evaluate quantity expressions using safe AST arithmetic.

        For items with a quantity_expression of type "formula", evaluates the
        expression against current selections. Falls back to the fixed quantity
        on any error (missing variable, parse error, negative result, etc.).
        """
        for item in items:
            if item.quantity_expression is None:
                continue
            expr_data = item.quantity_expression
            if expr_data.get("type") != "formula":
                continue
            formula_str = expr_data.get("expression")
            variables = expr_data.get("variables", {})
            if not formula_str or not variables:
                continue
            try:
                local_vars: dict[str, float] = {}
                for var_name, char_slug in variables.items():
                    val = selections.get(char_slug)
                    if val is None:
                        raise ValueError(
                            f"Missing selection for variable '{var_name}' (char: '{char_slug}')"
                        )
                    local_vars[var_name] = float(val)

                tree = ast.parse(formula_str, mode="eval")
                result = self._engine._safe_eval_ast(tree.body, local_vars)

                if result < 0:
                    logger.warning(
                        "quantity_expression_negative",
                        part_number=item.part_number,
                        result=result,
                        expression=formula_str,
                    )
                    continue  # keep original fixed quantity

                # Clamp to optional bounds
                min_qty = expr_data.get("min")
                max_qty = expr_data.get("max")
                if min_qty is not None:
                    result = max(result, float(min_qty))
                if max_qty is not None:
                    result = min(result, float(max_qty))

                item.quantity = Decimal(str(round(result, 10))).quantize(Decimal("0.0001"))
            except (ValueError, SyntaxError, TypeError, ZeroDivisionError, ArithmeticError) as exc:
                logger.warning(
                    "quantity_expression_eval_failed",
                    part_number=item.part_number,
                    expression=formula_str,
                    error=str(exc),
                )
                # Fallback: keep original fixed quantity
        return items

    @staticmethod
    def _calculate_tiered_price_all_units(
        quantity: Decimal, tiers: list[dict]
    ) -> Decimal:
        """All-units: entire quantity priced at the tier it falls into."""
        for tier in tiers:
            tier_min = _safe_decimal(tier["min"])
            tier_max = _safe_decimal(tier["max"]) if tier.get("max") is not None else None
            tier_price = _safe_decimal(tier["price"])
            if quantity >= tier_min and (tier_max is None or quantity <= tier_max):
                return quantity * tier_price
        # Quantity exceeds all tiers: use last tier
        if tiers:
            return quantity * _safe_decimal(tiers[-1]["price"])
        return Decimal("0")

    @staticmethod
    def _calculate_tiered_price_marginal(
        quantity: Decimal, tiers: list[dict]
    ) -> Decimal:
        """Marginal (incremental): units in each band priced at that band's rate."""
        total = Decimal("0")
        remaining = quantity
        for tier in tiers:
            if remaining <= 0:
                break
            tier_min = _safe_decimal(tier["min"])
            tier_max = _safe_decimal(tier["max"]) if tier.get("max") is not None else None
            tier_price = _safe_decimal(tier["price"])
            band_size = (tier_max - tier_min + 1) if tier_max is not None else remaining
            units_in_band = min(remaining, band_size)
            total += units_in_band * tier_price
            remaining -= units_in_band
        return total

    @staticmethod
    def _find_matching_tier(quantity: Decimal, tiers: list[dict]) -> dict | None:
        """Return the tier dict that the given quantity falls into."""
        for tier in tiers:
            tier_min = _safe_decimal(tier["min"])
            tier_max = _safe_decimal(tier["max"]) if tier.get("max") is not None else None
            if quantity >= tier_min and (tier_max is None or quantity <= tier_max):
                return {
                    "min": str(tier_min),
                    "max": str(tier_max) if tier_max is not None else None,
                    "price": str(tier["price"]),
                }
        return None

    async def _resolve_pricing(
        self,
        db: AsyncSession,
        session: ConfigurationSession,
        selections: dict[str, str],
        total_cost: Decimal,
        resolved_items_json: list[dict] | None = None,
    ) -> None:
        """Evaluate pricing rules and create/update ConfigurationPricing."""
        rules_result = await db.execute(
            select(PricingRule)
            .where(
                PricingRule.product_id == session.product_id,
                PricingRule.tenant_id == session.tenant_id,
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
                amount = _safe_decimal(expr.get("amount", 0))
                base_price += amount
                breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})

            elif rt == "option_surcharge":
                condition = expr.get("condition", {})
                if self._engine._evaluate_condition(condition, selections):
                    amount = _safe_decimal(expr.get("amount", 0))
                    total_adjustments += amount
                    breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})

            elif rt == "conditional":
                condition = expr.get("condition", {})
                if self._engine._evaluate_condition(condition, selections):
                    adj_type = expr.get("adjustment_type", "fixed")
                    amount = _safe_decimal(expr.get("amount", 0))
                    if adj_type == "percentage":
                        actual_amount = base_price * amount / Decimal("100")
                    else:
                        actual_amount = amount
                    total_adjustments += actual_amount
                    breakdown.append({"rule": rule.name, "type": rt, "amount": str(actual_amount)})

            elif rt == "volume_discount":
                amount = _safe_decimal(expr.get("amount", 0))
                total_adjustments += amount
                breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})

            elif rt == "formula":
                # Simplified formula support — expressions with characteristic values
                amount = _safe_decimal(expr.get("amount", 0))
                total_adjustments += amount
                breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})

            elif rt == "tiered":
                tiers = expr.get("tiers", [])
                if not tiers:
                    logger.warning("tiered_pricing_empty_tiers", rule_name=rule.name)
                    continue
                tier_model = expr.get("tier_model", "all_units")
                qty_source = expr.get("quantity_source", "bom_total")
                qty_key = expr.get("quantity_key")

                # Determine quantity
                quantity = Decimal("0")
                if qty_source == "bom_total" and resolved_items_json:
                    quantity = sum(
                        (Decimal(str(item.get("quantity", 0))) for item in resolved_items_json),
                        Decimal("0"),
                    )
                elif qty_source == "characteristic" and qty_key:
                    raw = selections.get(qty_key)
                    if raw is not None:
                        try:
                            quantity = Decimal(str(raw))
                        except InvalidOperation:
                            pass
                elif qty_source == "fixed" and qty_key is not None:
                    try:
                        quantity = Decimal(str(qty_key))
                    except InvalidOperation:
                        pass
                elif qty_source == "base_price":
                    quantity = base_price

                base_amount = _safe_decimal(expr.get("base_amount", 0))
                if tier_model == "marginal":
                    amount = base_amount + self._calculate_tiered_price_marginal(quantity, tiers)
                else:
                    amount = base_amount + self._calculate_tiered_price_all_units(quantity, tiers)

                total_adjustments += amount
                breakdown.append({
                    "rule": rule.name,
                    "type": rt,
                    "amount": str(amount),
                    "tier_model": tier_model,
                    "quantity_used": str(quantity),
                    "tier_applied": self._find_matching_tier(quantity, tiers),
                })

            elif rt == "margin":
                min_margin_pct = _safe_decimal(expr.get("min_margin_pct", 0))

        final_price = base_price + total_adjustments
        margin_amount = final_price - total_cost
        margin_percentage = (margin_amount / final_price * 100) if final_price > 0 else Decimal("0")
        is_profitable = margin_percentage >= min_margin_pct

        # Delete existing pricing (lock row to prevent concurrent race)
        existing = await db.execute(
            select(ConfigurationPricing).where(ConfigurationPricing.session_id == session.id)
            .with_for_update(skip_locked=False)
        )
        existing_pricing = existing.scalar_one_or_none()
        if existing_pricing:
            await db.delete(existing_pricing)
            await db.flush()

        pricing = ConfigurationPricing(
            tenant_id=session.tenant_id,
            session_id=session.id,
            currency="EUR",
            base_price=base_price,
            total_adjustments=total_adjustments,
            final_price=final_price,
            total_cost=total_cost,
            margin_amount=margin_amount,
            margin_percentage=margin_percentage,
            price_breakdown=breakdown,
            is_profitable=is_profitable,
        )
        db.add(pricing)
