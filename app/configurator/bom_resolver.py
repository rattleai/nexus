"""BOM resolution — filters a 150% super BOM to a configured 100% BOM."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.configurator.engine import ConfiguratorEngine
from app.db.models import (
    BOMHeader,
    BOMItem,
    BOMItemType,
    ConfigurationSession,
    ConfiguredBOM,
    ConfigurationPricing,
    PricingRule,
)

logger = structlog.stdlib.get_logger()


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
            .options(selectinload(BOMHeader.items).selectinload(BOMItem.children))
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
            }
            for r in resolved
        ]

        duration_ms = int((time.monotonic() - start) * 1000)

        # Delete existing resolved BOM if any
        existing = await db.execute(
            select(ConfiguredBOM).where(ConfiguredBOM.session_id == session_id)
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
        await self._resolve_pricing(db, session, selections, total_cost)

        await db.commit()
        await db.refresh(configured_bom)
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
            ))

            # Recurse into children
            if item.children:
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
                phantom_quantities[item.part_number] = item.quantity
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
        """Resolve quantity expressions (placeholder for formula evaluation)."""
        # Quantity expressions are evaluated in the BOM item model;
        # for now we use the fixed quantity. Full formula evaluation
        # will parse quantity_expression JSONB in a future iteration.
        return items

    async def _resolve_pricing(
        self,
        db: AsyncSession,
        session: ConfigurationSession,
        selections: dict[str, str],
        total_cost: Decimal,
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
                amount = Decimal(str(expr.get("amount", 0)))
                base_price += amount
                breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})

            elif rt == "option_surcharge":
                condition = expr.get("condition", {})
                if self._engine._evaluate_condition(condition, selections):
                    amount = Decimal(str(expr.get("amount", 0)))
                    total_adjustments += amount
                    breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})

            elif rt == "conditional":
                condition = expr.get("condition", {})
                if self._engine._evaluate_condition(condition, selections):
                    adj_type = expr.get("adjustment_type", "fixed")
                    amount = Decimal(str(expr.get("amount", 0)))
                    if adj_type == "percentage":
                        actual_amount = base_price * amount / Decimal("100")
                    else:
                        actual_amount = amount
                    total_adjustments += actual_amount
                    breakdown.append({"rule": rule.name, "type": rt, "amount": str(actual_amount)})

            elif rt == "volume_discount":
                amount = Decimal(str(expr.get("amount", 0)))
                total_adjustments += amount
                breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})

            elif rt == "formula":
                # Simplified formula support — expressions with characteristic values
                amount = Decimal(str(expr.get("amount", 0)))
                total_adjustments += amount
                breakdown.append({"rule": rule.name, "type": rt, "amount": str(amount)})

            elif rt == "margin":
                min_margin_pct = Decimal(str(expr.get("min_margin_pct", 0)))

        final_price = base_price + total_adjustments
        margin_amount = final_price - total_cost
        margin_percentage = (margin_amount / final_price * 100) if final_price > 0 else Decimal("0")
        is_profitable = margin_percentage >= min_margin_pct

        # Delete existing pricing
        existing = await db.execute(
            select(ConfigurationPricing).where(ConfigurationPricing.session_id == session.id)
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
