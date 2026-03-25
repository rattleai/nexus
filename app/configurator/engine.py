"""Constraint-based configuration engine using arc-consistency (AC-3 variant).

Stateless: all state lives in ConfigurationSession/Selections in the DB.
Each operation loads the current state, computes, and returns the result.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Characteristic,
    CharacteristicAssignment,
    CharacteristicValue,
    ConfigurationSelection,
    ConfigurationSession,
    ConfigurationStatus,
    ConstraintRule,
    ConstraintType,
    VariantTable,
)

logger = structlog.stdlib.get_logger()


@dataclass
class ValidationError:
    characteristic_slug: str | None = None
    rule_id: str | None = None
    rule_name: str | None = None
    error_type: str = ""
    message: str = ""


@dataclass
class SelectionResult:
    available_domains: dict[str, list[str]] = field(default_factory=dict)
    auto_set_values: dict[str, str] = field(default_factory=dict)
    excluded_values: dict[str, list[str]] = field(default_factory=dict)
    validation_errors: list[ValidationError] = field(default_factory=list)
    is_valid: bool = False
    is_complete: bool = False


@dataclass
class PropagationResult:
    domains: dict[str, set[str]]
    auto_set: dict[str, str] = field(default_factory=dict)
    excluded: dict[str, list[str]] = field(default_factory=dict)
    contradictions: list[str] = field(default_factory=list)


class ConfiguratorEngine:
    """Constraint evaluation and propagation engine."""

    async def initialize_domains(
        self, db: AsyncSession, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> dict[str, list[str]]:
        """Build initial (unconstrained) domains for all product characteristics."""
        assignments = await db.execute(
            select(CharacteristicAssignment)
            .where(CharacteristicAssignment.product_id == product_id, CharacteristicAssignment.tenant_id == tenant_id)
            .options(selectinload(CharacteristicAssignment.characteristic).selectinload(Characteristic.values))
        )

        domains: dict[str, list[str]] = {}
        for assignment in assignments.scalars().all():
            char = assignment.characteristic
            if char.deleted_at is not None:
                continue
            if char.char_type.value == "enum":
                domains[char.slug] = [v.value for v in char.values]
            elif char.char_type.value == "boolean":
                domains[char.slug] = ["true", "false"]
            elif char.char_type.value in ("numeric", "text"):
                domains[char.slug] = ["__any__"]
        return domains

    async def apply_selection(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        characteristic_slug: str,
        value: str,
    ) -> SelectionResult:
        """Apply a user selection and propagate constraints."""
        session = await self._load_session(db, session_id)
        if not session:
            return SelectionResult(validation_errors=[ValidationError(error_type="not_found", message="Session not found")])

        if session.status == ConfigurationStatus.LOCKED:
            return SelectionResult(validation_errors=[ValidationError(error_type="locked", message="Session is locked")])

        # Load product characteristics and constraints
        char_map = await self._load_characteristics(db, session.product_id, session.tenant_id)
        constraints = await self._load_constraints(db, session.product_id, session.tenant_id)
        variant_tables = await self._load_variant_tables(db, session.product_id, session.tenant_id)

        # Resolve characteristic
        if characteristic_slug not in char_map:
            return SelectionResult(
                validation_errors=[ValidationError(
                    characteristic_slug=characteristic_slug,
                    error_type="unknown_characteristic",
                    message=f"Characteristic '{characteristic_slug}' not found on this product",
                )]
            )

        char = char_map[characteristic_slug]

        # Validate value is in domain for enum types
        if char.char_type.value == "enum":
            allowed = {v.value for v in char.values}
            if value not in allowed:
                return SelectionResult(
                    validation_errors=[ValidationError(
                        characteristic_slug=characteristic_slug,
                        error_type="invalid_value",
                        message=f"Value '{value}' is not allowed for '{characteristic_slug}'",
                    )]
                )
        elif char.char_type.value == "numeric":
            try:
                num_val = float(value)
            except ValueError:
                return SelectionResult(
                    validation_errors=[ValidationError(
                        characteristic_slug=characteristic_slug,
                        error_type="invalid_value",
                        message=f"Value '{value}' is not a valid number",
                    )]
                )
            if char.numeric_min is not None and num_val < char.numeric_min:
                return SelectionResult(
                    validation_errors=[ValidationError(
                        characteristic_slug=characteristic_slug,
                        error_type="out_of_range",
                        message=f"Value {num_val} is below minimum {char.numeric_min}",
                    )]
                )
            if char.numeric_max is not None and num_val > char.numeric_max:
                return SelectionResult(
                    validation_errors=[ValidationError(
                        characteristic_slug=characteristic_slug,
                        error_type="out_of_range",
                        message=f"Value {num_val} is above maximum {char.numeric_max}",
                    )]
                )

        # Upsert selection (remove existing for single-select, add for multi-select)
        if not char.is_multi_select:
            existing = [s for s in session.selections if s.characteristic_id == char.id and not s.is_auto_set]
            for s in existing:
                await db.delete(s)

        new_selection = ConfigurationSelection(
            tenant_id=session.tenant_id,
            session_id=session.id,
            characteristic_id=char.id,
            value=value,
            is_auto_set=False,
        )
        db.add(new_selection)
        await db.flush()

        # Reload selections after upsert
        await db.refresh(session, attribute_names=["selections"])

        # Build current selections map
        selections = self._build_selections_map(session.selections, char_map)

        # Initialize domains and propagate
        domains = self._build_initial_domains(char_map)
        result = self._propagate(domains, selections, constraints, variant_tables, {characteristic_slug})

        # Handle auto-set values
        for slug, auto_value in result.auto_set.items():
            if slug in char_map and slug not in selections:
                auto_char = char_map[slug]
                auto_sel = ConfigurationSelection(
                    tenant_id=session.tenant_id,
                    session_id=session.id,
                    characteristic_id=auto_char.id,
                    value=auto_value,
                    is_auto_set=True,
                )
                db.add(auto_sel)

        # Build validation errors from contradictions
        errors = [
            ValidationError(characteristic_slug=c, error_type="domain_empty", message=f"No valid values remain for '{c}'")
            for c in result.contradictions
        ]

        # Check completeness
        is_complete = self._check_completeness(char_map, selections, result.auto_set)
        is_valid = len(errors) == 0

        # Update session state
        session.available_domains = {k: sorted(v) for k, v in result.domains.items()}
        session.is_valid = is_valid
        session.is_complete = is_complete
        session.validation_errors = [
            {"characteristic_slug": e.characteristic_slug, "error_type": e.error_type, "message": e.message}
            for e in errors
        ]
        if is_valid and is_complete:
            session.status = ConfigurationStatus.COMPLETE
        elif not is_valid:
            session.status = ConfigurationStatus.INVALID
        else:
            session.status = ConfigurationStatus.IN_PROGRESS

        await db.commit()
        await db.refresh(session, attribute_names=["selections"])

        return SelectionResult(
            available_domains={k: sorted(v) for k, v in result.domains.items()},
            auto_set_values=result.auto_set,
            excluded_values=result.excluded,
            validation_errors=errors,
            is_valid=is_valid,
            is_complete=is_complete,
        )

    async def remove_selection(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        characteristic_id: uuid.UUID,
    ) -> SelectionResult:
        """Remove a selection and re-propagate from scratch."""
        session = await self._load_session(db, session_id)
        if not session:
            return SelectionResult(validation_errors=[ValidationError(error_type="not_found", message="Session not found")])

        # Remove user selection(s) for this characteristic
        to_remove = [s for s in session.selections if s.characteristic_id == characteristic_id and not s.is_auto_set]
        for s in to_remove:
            await db.delete(s)

        # Remove all auto-set selections (will be re-computed)
        auto_set = [s for s in session.selections if s.is_auto_set]
        for s in auto_set:
            await db.delete(s)

        await db.flush()
        await db.refresh(session, attribute_names=["selections"])

        char_map = await self._load_characteristics(db, session.product_id, session.tenant_id)
        constraints = await self._load_constraints(db, session.product_id, session.tenant_id)
        variant_tables = await self._load_variant_tables(db, session.product_id, session.tenant_id)

        # Re-propagate from remaining selections
        selections = self._build_selections_map(session.selections, char_map)
        domains = self._build_initial_domains(char_map)

        all_chars = set(selections.keys())
        result = self._propagate(domains, selections, constraints, variant_tables, all_chars)

        # Re-add auto-set values
        for slug, auto_value in result.auto_set.items():
            if slug in char_map and slug not in selections:
                auto_char = char_map[slug]
                auto_sel = ConfigurationSelection(
                    tenant_id=session.tenant_id,
                    session_id=session.id,
                    characteristic_id=auto_char.id,
                    value=auto_value,
                    is_auto_set=True,
                )
                db.add(auto_sel)

        errors = [
            ValidationError(characteristic_slug=c, error_type="domain_empty", message=f"No valid values remain for '{c}'")
            for c in result.contradictions
        ]

        is_complete = self._check_completeness(char_map, selections, result.auto_set)
        is_valid = len(errors) == 0

        session.available_domains = {k: sorted(v) for k, v in result.domains.items()}
        session.is_valid = is_valid
        session.is_complete = is_complete
        session.validation_errors = [
            {"characteristic_slug": e.characteristic_slug, "error_type": e.error_type, "message": e.message}
            for e in errors
        ]
        session.status = (
            ConfigurationStatus.COMPLETE if is_valid and is_complete
            else ConfigurationStatus.INVALID if not is_valid
            else ConfigurationStatus.IN_PROGRESS
        )

        await db.commit()
        await db.refresh(session, attribute_names=["selections"])

        return SelectionResult(
            available_domains={k: sorted(v) for k, v in result.domains.items()},
            auto_set_values=result.auto_set,
            excluded_values=result.excluded,
            validation_errors=errors,
            is_valid=is_valid,
            is_complete=is_complete,
        )

    # ── Pure computation ─────────────────────────────────

    def _propagate(
        self,
        domains: dict[str, set[str]],
        selections: dict[str, str | list[str]],
        constraints: list[ConstraintRule],
        variant_tables: dict[str, VariantTable],
        changed_chars: set[str],
    ) -> PropagationResult:
        """Run arc-consistency propagation loop. Pure function, no DB access."""
        auto_set: dict[str, str] = {}
        excluded: dict[str, list[str]] = defaultdict(list)
        contradictions: list[str] = []

        # Set selected values as single-element domains
        for slug, val in selections.items():
            if slug in domains and not isinstance(val, list):
                domains[slug] = {val}

        # Build constraint index: char_slug -> [constraints referencing it]
        char_constraints: dict[str, list[ConstraintRule]] = defaultdict(list)
        for c in constraints:
            referenced = self._extract_referenced_chars(c.expression)
            for ref_char in referenced:
                char_constraints[ref_char].append(c)

        queue = set(changed_chars)
        max_iterations = len(domains) * len(constraints) + 100  # Safety bound

        iteration = 0
        while queue and iteration < max_iterations:
            iteration += 1
            char_slug = queue.pop()

            for constraint in char_constraints.get(char_slug, []):
                if not constraint.is_active:
                    continue
                # Check effectivity
                now = datetime.now(UTC)
                if constraint.effective_from and now < constraint.effective_from:
                    continue
                if constraint.effective_to and now > constraint.effective_to:
                    continue

                ct = constraint.constraint_type
                expr = constraint.expression

                if ct == ConstraintType.REQUIRES:
                    if self._evaluate_condition(expr.get("if", {}), selections):
                        then_clause = expr.get("then", {})
                        target_char = then_clause.get("char")
                        if target_char and target_char in domains:
                            required_values = then_clause.get("value")
                            if isinstance(required_values, str):
                                required_values = [required_values]
                            if required_values:
                                old = domains[target_char]
                                new = old & set(required_values)
                                if new != old:
                                    domains[target_char] = new
                                    queue.add(target_char)

                elif ct == ConstraintType.EXCLUDES:
                    if self._evaluate_condition(expr.get("if", {}), selections):
                        then_clause = expr.get("then", {})
                        target_char = then_clause.get("char")
                        if target_char and target_char in domains:
                            excluded_values = then_clause.get("value")
                            if isinstance(excluded_values, str):
                                excluded_values = [excluded_values]
                            if excluded_values:
                                old = domains[target_char]
                                new = old - set(excluded_values)
                                if new != old:
                                    excluded[target_char].extend(excluded_values)
                                    domains[target_char] = new
                                    queue.add(target_char)

                elif ct == ConstraintType.SELECTION_CONDITION:
                    condition = expr.get("condition", {})
                    if not self._evaluate_condition(condition, selections):
                        target = expr.get("target", {})
                        target_char = target.get("char")
                        target_value = target.get("value")
                        if target_char and target_value and target_char in domains:
                            old = domains[target_char]
                            new = old - {target_value}
                            if new != old:
                                excluded[target_char].append(target_value)
                                domains[target_char] = new
                                queue.add(target_char)

                elif ct == ConstraintType.DEFAULT_VALUE:
                    if self._evaluate_condition(expr.get("if", {}), selections):
                        target_char = expr.get("target")
                        default_val = expr.get("value")
                        if target_char and default_val and target_char not in selections:
                            auto_set[target_char] = default_val
                            if target_char in domains:
                                domains[target_char] = {default_val}
                                queue.add(target_char)

                elif ct == ConstraintType.TABLE:
                    table_id = expr.get("table_id")
                    if table_id and table_id in variant_tables:
                        vt = variant_tables[table_id]
                        output_values = self._lookup_variant_table(vt, selections)
                        for out_char, out_vals in output_values.items():
                            if out_char in domains:
                                old = domains[out_char]
                                new = old & set(out_vals)
                                if new != old:
                                    domains[out_char] = new
                                    queue.add(out_char)

        # Post-propagation: detect contradictions and auto-set forced values
        for slug, domain in domains.items():
            if "__any__" in domain:
                continue
            if len(domain) == 0:
                contradictions.append(slug)
            elif len(domain) == 1 and slug not in selections and slug not in auto_set:
                auto_set[slug] = next(iter(domain))

        return PropagationResult(
            domains=domains,
            auto_set=auto_set,
            excluded=dict(excluded),
            contradictions=contradictions,
        )

    def _evaluate_condition(
        self, condition: dict, selections: dict[str, str | list[str]]
    ) -> bool:
        """Evaluate a JSONB condition expression against current selections."""
        if not condition:
            return True

        op = condition.get("op")
        char_slug = condition.get("char")

        # Compound operators
        if op == "and":
            return all(self._evaluate_condition(c, selections) for c in condition.get("conditions", []))
        if op == "or":
            return any(self._evaluate_condition(c, selections) for c in condition.get("conditions", []))
        if op == "not":
            return not self._evaluate_condition(condition.get("condition", {}), selections)

        # Leaf operators
        if not char_slug:
            return True

        current_value = selections.get(char_slug)
        if current_value is None:
            return False

        expected = condition.get("value")

        if op == "eq":
            return current_value == expected
        if op == "neq":
            return current_value != expected
        if op == "in":
            if isinstance(expected, list):
                return current_value in expected
            return False
        if op == "not_in":
            if isinstance(expected, list):
                return current_value not in expected
            return True
        if op in ("gt", "gte", "lt", "lte"):
            try:
                cv = float(current_value) if isinstance(current_value, str) else current_value
                ev = float(expected) if isinstance(expected, str) else expected
            except (ValueError, TypeError):
                return False
            if op == "gt":
                return cv > ev
            if op == "gte":
                return cv >= ev
            if op == "lt":
                return cv < ev
            if op == "lte":
                return cv <= ev

        return True

    def _extract_referenced_chars(self, expression: dict) -> set[str]:
        """Extract all characteristic slugs referenced in an expression."""
        chars = set()
        if "char" in expression:
            chars.add(expression["char"])
        if "target" in expression and isinstance(expression["target"], dict):
            if "char" in expression["target"]:
                chars.add(expression["target"]["char"])
        for key in ("if", "then", "condition"):
            if key in expression and isinstance(expression[key], dict):
                chars |= self._extract_referenced_chars(expression[key])
        for key in ("conditions",):
            if key in expression and isinstance(expression[key], list):
                for sub in expression[key]:
                    if isinstance(sub, dict):
                        chars |= self._extract_referenced_chars(sub)
        return chars

    def _lookup_variant_table(
        self, table: VariantTable, selections: dict[str, str | list[str]]
    ) -> dict[str, list[str]]:
        """Look up matching rows in a variant table given current selections."""
        output_values: dict[str, list[str]] = defaultdict(list)
        input_cols = table.input_columns
        output_cols = table.output_columns

        for row in table.rows:
            match = True
            for col in input_cols:
                if col in selections:
                    if str(row.get(col)) != str(selections[col]):
                        match = False
                        break
            if match:
                for col in output_cols:
                    if col in row:
                        output_values[col].append(str(row[col]))

        return dict(output_values)

    # ── Helpers ──────────────────────────────────────────

    async def _load_session(self, db: AsyncSession, session_id: uuid.UUID) -> ConfigurationSession | None:
        result = await db.execute(
            select(ConfigurationSession)
            .where(ConfigurationSession.id == session_id)
            .options(selectinload(ConfigurationSession.selections))
        )
        return result.scalar_one_or_none()

    async def _load_characteristics(
        self, db: AsyncSession, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> dict[str, Characteristic]:
        result = await db.execute(
            select(CharacteristicAssignment)
            .where(CharacteristicAssignment.product_id == product_id, CharacteristicAssignment.tenant_id == tenant_id)
            .options(selectinload(CharacteristicAssignment.characteristic).selectinload(Characteristic.values))
        )
        char_map = {}
        for assignment in result.scalars().all():
            char = assignment.characteristic
            if char.deleted_at is None:
                char_map[char.slug] = char
        return char_map

    async def _load_constraints(
        self, db: AsyncSession, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[ConstraintRule]:
        result = await db.execute(
            select(ConstraintRule)
            .where(
                ConstraintRule.product_id == product_id,
                ConstraintRule.tenant_id == tenant_id,
                ConstraintRule.deleted_at.is_(None),
                ConstraintRule.is_active.is_(True),
            )
            .order_by(ConstraintRule.priority.desc())
        )
        return list(result.scalars().all())

    async def _load_variant_tables(
        self, db: AsyncSession, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> dict[str, VariantTable]:
        result = await db.execute(
            select(VariantTable).where(
                VariantTable.product_id == product_id, VariantTable.tenant_id == tenant_id
            )
        )
        return {str(t.id): t for t in result.scalars().all()}

    def _build_selections_map(
        self, selections: list[ConfigurationSelection], char_map: dict[str, Characteristic]
    ) -> dict[str, str]:
        """Build {slug: value} from DB selections."""
        id_to_slug = {char.id: slug for slug, char in char_map.items()}
        result = {}
        for sel in selections:
            slug = id_to_slug.get(sel.characteristic_id)
            if slug:
                result[slug] = sel.value
        return result

    def _build_initial_domains(self, char_map: dict[str, Characteristic]) -> dict[str, set[str]]:
        """Build full (unconstrained) domains from characteristic definitions."""
        domains: dict[str, set[str]] = {}
        for slug, char in char_map.items():
            if char.char_type.value == "enum":
                domains[slug] = {v.value for v in char.values}
            elif char.char_type.value == "boolean":
                domains[slug] = {"true", "false"}
            else:
                domains[slug] = {"__any__"}
        return domains

    def _check_completeness(
        self,
        char_map: dict[str, Characteristic],
        selections: dict[str, str],
        auto_set: dict[str, str],
    ) -> bool:
        """Check if all required characteristics have a selection."""
        all_selected = {**selections, **auto_set}
        for slug, char in char_map.items():
            if char.is_required and slug not in all_selected:
                return False
        return True
