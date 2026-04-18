"""Constraint-based configuration engine using arc-consistency (AC-3 variant).

Stateless: all state lives in ConfigurationSession/Selections in the DB.
Each operation loads the current state, computes, and returns the result.
"""

from __future__ import annotations

import ast
import contextlib
import math
import operator
import time as _time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.apps.cpq.models.configurator import (
    ConfigurationSelection,
    ConfigurationSession,
    ConfigurationStatus,
)
from app.apps.cpq.models.product import (
    Characteristic,
    CharacteristicAssignment,
    ConstraintRule,
    ConstraintType,
    VariantTable,
)
from app.core.metrics import (
    CONFIGURATOR_CONTRADICTIONS,
    CONFIGURATOR_PROPAGATION_DURATION,
    CONFIGURATOR_PROPAGATION_ITERATIONS,
)

logger = structlog.stdlib.get_logger()


class CharacteristicInfo:
    """Characteristic + product-level assignment overrides (cardinality, etc.).

    Delegates attribute access to the inner Characteristic ORM object so that
    existing code accessing .char_type, .values, .numeric_min etc. continues to
    work without changes.
    """

    __slots__ = ("characteristic", "max_select", "min_select")

    def __init__(
        self,
        characteristic: Characteristic,
        min_select: int | None = None,
        max_select: int | None = None,
    ):
        self.characteristic = characteristic
        self.min_select = min_select
        self.max_select = max_select

    def __getattr__(self, name: str):
        return getattr(self.characteristic, name)


@dataclass(frozen=True)
class NumericInterval:
    """Represents a numeric domain as a bounded interval with optional step."""

    min: float | None = None  # None = unbounded below
    max: float | None = None  # None = unbounded above
    step: float | None = None  # None = continuous

    def is_empty(self) -> bool:
        if self.min is not None and self.max is not None:
            return self.min > self.max + 1e-9
        return False

    def is_single_point(self) -> bool:
        if self.min is not None and self.max is not None:
            return math.isclose(self.min, self.max, rel_tol=1e-9, abs_tol=1e-9)
        return False

    def intersect(self, other: NumericInterval) -> NumericInterval:
        new_min = self.min
        if other.min is not None:
            new_min = other.min if new_min is None else max(new_min, other.min)
        new_max = self.max
        if other.max is not None:
            new_max = other.max if new_max is None else min(new_max, other.max)
        new_step = self.step or other.step
        return NumericInterval(min=new_min, max=new_max, step=new_step)

    def contains(self, value: float) -> bool:
        if self.min is not None and value < self.min - 1e-9:
            return False
        if self.max is not None and value > self.max + 1e-9:
            return False
        if self.step is not None and self.min is not None:
            remainder = (value - self.min) % self.step
            if not (remainder < 1e-9 or abs(remainder - self.step) < 1e-9):
                return False
        return True

    def to_dict(self) -> dict:
        return {"type": "numeric", "min": self.min, "max": self.max, "step": self.step}


# Type aliases for domain representation
DomainValue = set[str] | NumericInterval
DomainMap = dict[str, DomainValue]

SNAPSHOT_SCHEMA_VERSION = 1


class _CharTypeProxy:
    """Mimics CharacteristicType enum for snapshot-loaded chars."""

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value


class _ValueProxy:
    """Mimics CharacteristicValue for snapshot-loaded chars."""

    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value


@dataclass
class SnapshotCharacteristic:
    """Lightweight characteristic from a pre-compiled snapshot."""

    id: str
    slug: str
    name: str
    char_type: _CharTypeProxy
    values: list[_ValueProxy]
    is_required: bool
    is_multi_select: bool
    numeric_min: float | None
    numeric_max: float | None
    numeric_step: float | None = None
    unit: str | None = None
    default_value: str | None = None
    deleted_at: object = None


@dataclass
class SnapshotConstraint:
    """Lightweight constraint from a pre-compiled snapshot."""

    id: str
    name: str
    constraint_type: ConstraintType
    expression: dict
    priority: int
    is_active: bool
    effective_from: datetime | None = None
    effective_to: datetime | None = None


@dataclass
class ValidationError:
    characteristic_slug: str | None = None
    rule_id: str | None = None
    rule_name: str | None = None
    error_type: str = ""
    message: str = ""


@dataclass
class ConflictStep:
    """One step in the conflict explanation trace."""

    rule_id: str | None
    rule_name: str | None
    constraint_type: str
    target_char: str
    removed_values: list[str]
    triggered_by: dict[str, str]  # {char_slug: selected_value} that activated the rule


@dataclass
class ConflictExplanation:
    """Full explanation of why a characteristic's domain became empty."""

    characteristic: str
    trace: list[ConflictStep] = field(default_factory=list)
    contributing_selections: dict[str, str] = field(default_factory=dict)


@dataclass
class SelectionResult:
    available_domains: dict[str, list[str]] = field(default_factory=dict)
    auto_set_values: dict[str, str] = field(default_factory=dict)
    excluded_values: dict[str, list[str]] = field(default_factory=dict)
    validation_errors: list[ValidationError] = field(default_factory=list)
    conflict_explanations: list[ConflictExplanation] = field(default_factory=list)
    is_valid: bool = False
    is_complete: bool = False


@dataclass
class DomainPruneRecord:
    """Records a single domain pruning event during propagation."""

    rule_id: str | None
    rule_name: str | None
    constraint_type: str
    target_char: str
    removed_values: list[str]
    triggered_by: dict[str, str]  # selections that caused the rule to fire


@dataclass
class PropagationResult:
    domains: dict[str, set[str]]
    auto_set: dict[str, str] = field(default_factory=dict)
    excluded: dict[str, list[str]] = field(default_factory=dict)
    contradictions: list[str] = field(default_factory=list)
    prune_history: list[DomainPruneRecord] = field(default_factory=list)
    conflict_explanations: list[ConflictExplanation] = field(default_factory=list)


class _ProductDataCache:
    """In-memory TTL cache for product configuration data (characteristics, constraints, tables).

    Avoids 3 DB round-trips per selection for data that rarely changes.
    Invalidate via ConfiguratorEngine.invalidate_product_cache() on CRUD operations.
    """

    def __init__(self, ttl_seconds: int = 600):
        self._ttl = ttl_seconds
        self._chars: dict[str, tuple[float, dict]] = {}  # key -> (timestamp, data)
        self._constraints: dict[str, tuple[float, list]] = {}
        self._vtables: dict[str, tuple[float, dict]] = {}

    def _key(self, product_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
        return f"{product_id}:{tenant_id}"

    def _is_valid(self, entry: tuple[float, object] | None) -> bool:
        if entry is None:
            return False
        import time

        return (time.monotonic() - entry[0]) < self._ttl

    def get_chars(self, product_id: uuid.UUID, tenant_id: uuid.UUID):
        entry = self._chars.get(self._key(product_id, tenant_id))
        return entry[1] if self._is_valid(entry) else None

    def set_chars(self, product_id: uuid.UUID, tenant_id: uuid.UUID, data):
        import time

        self._chars[self._key(product_id, tenant_id)] = (time.monotonic(), data)

    def get_constraints(self, product_id: uuid.UUID, tenant_id: uuid.UUID):
        entry = self._constraints.get(self._key(product_id, tenant_id))
        return entry[1] if self._is_valid(entry) else None

    def set_constraints(self, product_id: uuid.UUID, tenant_id: uuid.UUID, data):
        import time

        self._constraints[self._key(product_id, tenant_id)] = (time.monotonic(), data)

    def get_vtables(self, product_id: uuid.UUID, tenant_id: uuid.UUID):
        entry = self._vtables.get(self._key(product_id, tenant_id))
        return entry[1] if self._is_valid(entry) else None

    def set_vtables(self, product_id: uuid.UUID, tenant_id: uuid.UUID, data):
        import time

        self._vtables[self._key(product_id, tenant_id)] = (time.monotonic(), data)

    def invalidate(self, product_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        key = self._key(product_id, tenant_id)
        self._chars.pop(key, None)
        self._constraints.pop(key, None)
        self._vtables.pop(key, None)

    def invalidate_all(self) -> None:
        self._chars.clear()
        self._constraints.clear()
        self._vtables.clear()


# Module-level singleton cache shared across engine instances
_product_cache = _ProductDataCache(ttl_seconds=600)


class ConfiguratorEngine:
    """Constraint evaluation and propagation engine."""

    @staticmethod
    def invalidate_product_cache(product_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Invalidate cached product data. Call on characteristic/constraint/vtable CRUD."""
        _product_cache.invalidate(product_id, tenant_id)

    async def initialize_domains(
        self, db: AsyncSession, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> dict[str, list[str] | dict]:
        """Build initial (unconstrained) domains for all product characteristics."""
        assignments = await db.execute(
            select(CharacteristicAssignment)
            .where(CharacteristicAssignment.product_id == product_id, CharacteristicAssignment.tenant_id == tenant_id)
            .options(selectinload(CharacteristicAssignment.characteristic).selectinload(Characteristic.values))
        )

        domains: dict[str, list[str] | dict] = {}
        for assignment in assignments.scalars().all():
            char = assignment.characteristic
            if char.deleted_at is not None:
                continue
            if char.char_type.value == "enum":
                domains[char.slug] = [v.value for v in char.values]
            elif char.char_type.value == "boolean":
                domains[char.slug] = ["true", "false"]
            elif char.char_type.value == "numeric":
                domains[char.slug] = {
                    "type": "numeric",
                    "min": char.numeric_min,
                    "max": char.numeric_max,
                    "step": char.numeric_step,
                }
            else:  # text
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
        session = await self._load_session(db, session_id, for_update=True)
        if not session:
            return SelectionResult(
                validation_errors=[ValidationError(error_type="not_found", message="Session not found")]
            )

        if session.status == ConfigurationStatus.LOCKED:
            return SelectionResult(
                validation_errors=[ValidationError(error_type="locked", message="Session is locked")]
            )

        # Load product characteristics and constraints
        char_map = await self._load_characteristics(db, session.product_id, session.tenant_id)
        constraints = await self._load_constraints(db, session.product_id, session.tenant_id)
        variant_tables = await self._load_variant_tables(db, session.product_id, session.tenant_id)

        # Resolve characteristic
        if characteristic_slug not in char_map:
            return SelectionResult(
                validation_errors=[
                    ValidationError(
                        characteristic_slug=characteristic_slug,
                        error_type="unknown_characteristic",
                        message=f"Characteristic '{characteristic_slug}' not found on this product",
                    )
                ]
            )

        char = char_map[characteristic_slug]

        # Validate value is in domain for enum types
        if char.char_type.value == "enum":
            allowed = {v.value for v in char.values}
            if value not in allowed:
                return SelectionResult(
                    validation_errors=[
                        ValidationError(
                            characteristic_slug=characteristic_slug,
                            error_type="invalid_value",
                            message=f"Value '{value}' is not allowed for '{characteristic_slug}'",
                        )
                    ]
                )
        elif char.char_type.value == "numeric":
            try:
                num_val = float(value)
            except ValueError:
                return SelectionResult(
                    validation_errors=[
                        ValidationError(
                            characteristic_slug=characteristic_slug,
                            error_type="invalid_value",
                            message=f"Value '{value}' is not a valid number",
                        )
                    ]
                )
            if char.numeric_min is not None and num_val < char.numeric_min:
                return SelectionResult(
                    validation_errors=[
                        ValidationError(
                            characteristic_slug=characteristic_slug,
                            error_type="out_of_range",
                            message=f"Value {num_val} is below minimum {char.numeric_min}",
                        )
                    ]
                )
            if char.numeric_max is not None and num_val > char.numeric_max:
                return SelectionResult(
                    validation_errors=[
                        ValidationError(
                            characteristic_slug=characteristic_slug,
                            error_type="out_of_range",
                            message=f"Value {num_val} is above maximum {char.numeric_max}",
                        )
                    ]
                )

        # Upsert selection (remove existing for single-select, add for multi-select)
        if not char.is_multi_select:
            existing = [s for s in session.selections if s.characteristic_id == char.id and not s.is_auto_set]
            for s in existing:
                await db.delete(s)
        else:
            # Enforce max_select cardinality for multi-select
            char_info = char_map[characteristic_slug]
            if char_info.max_select is not None:
                existing_count = sum(
                    1 for s in session.selections if s.characteristic_id == char.id and not s.is_auto_set
                )
                if existing_count >= char_info.max_select:
                    return SelectionResult(
                        validation_errors=[
                            ValidationError(
                                characteristic_slug=characteristic_slug,
                                error_type="max_cardinality_exceeded",
                                message=f"Maximum {char_info.max_select} selections allowed for '{characteristic_slug}', already have {existing_count}",
                            )
                        ]
                    )

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

        # Build validation errors from contradictions (with explanation context)
        errors = []
        for explanation in result.conflict_explanations:
            rules_involved = [s.rule_name or s.rule_id or "unknown" for s in explanation.trace]
            detail = f"No valid values remain for '{explanation.characteristic}'"
            if rules_involved:
                detail += f". Caused by rules: {', '.join(rules_involved)}"
            if explanation.contributing_selections:
                sel_parts = [f"{k}={v}" for k, v in explanation.contributing_selections.items()]
                detail += f". Contributing selections: {', '.join(sel_parts)}"
            errors.append(
                ValidationError(
                    characteristic_slug=explanation.characteristic,
                    error_type="domain_empty",
                    message=detail,
                )
            )

        # Check completeness
        is_complete = self._check_completeness(char_map, selections, result.auto_set)
        is_valid = len(errors) == 0

        # Update session state
        session.available_domains = self._serialize_domains(result.domains)
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

        await db.flush()
        await db.refresh(session, attribute_names=["selections"])
        await db.commit()

        return SelectionResult(
            available_domains=self._serialize_domains(result.domains),
            auto_set_values=result.auto_set,
            excluded_values=result.excluded,
            validation_errors=errors,
            conflict_explanations=result.conflict_explanations,
            is_valid=is_valid,
            is_complete=is_complete,
        )

    async def apply_selections_batch(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        selection_pairs: list[tuple[str, str]],
    ) -> SelectionResult:
        """Apply multiple selections at once, running propagation only ONCE.

        Used for template application and bulk imports to avoid N separate
        load-propagate-commit cycles.
        """
        session = await self._load_session(db, session_id, for_update=True)
        if not session:
            return SelectionResult(
                validation_errors=[ValidationError(error_type="not_found", message="Session not found")]
            )

        if session.status == ConfigurationStatus.LOCKED:
            return SelectionResult(
                validation_errors=[ValidationError(error_type="locked", message="Session is locked")]
            )

        char_map = await self._load_characteristics(db, session.product_id, session.tenant_id)
        constraints = await self._load_constraints(db, session.product_id, session.tenant_id)
        variant_tables = await self._load_variant_tables(db, session.product_id, session.tenant_id)

        changed_chars: set[str] = set()

        for slug, value in selection_pairs:
            if slug not in char_map:
                continue  # skip unknown chars in template
            char = char_map[slug]

            # Validate value for enum types
            if char.char_type.value == "enum":
                allowed = {v.value for v in char.values}
                if value not in allowed:
                    continue

            # Upsert selection
            if not char.is_multi_select:
                existing = [s for s in session.selections if s.characteristic_id == char.id and not s.is_auto_set]
                for s in existing:
                    await db.delete(s)
            else:
                # Enforce max_select cardinality for multi-select
                if char.max_select is not None:
                    existing_count = sum(
                        1 for s in session.selections if s.characteristic_id == char.id and not s.is_auto_set
                    )
                    if existing_count >= char.max_select:
                        logger.warning(
                            "batch_apply_cardinality_exceeded",
                            slug=slug,
                            max_select=char.max_select,
                            existing=existing_count,
                        )
                        continue

            new_sel = ConfigurationSelection(
                tenant_id=session.tenant_id,
                session_id=session.id,
                characteristic_id=char.id,
                value=value,
                is_auto_set=False,
            )
            db.add(new_sel)
            changed_chars.add(slug)

        await db.flush()
        await db.refresh(session, attribute_names=["selections"])

        # Build selections and propagate ONCE
        selections = self._build_selections_map(session.selections, char_map)
        domains = self._build_initial_domains(char_map)
        result = self._propagate(domains, selections, constraints, variant_tables, changed_chars)

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
        errors = []
        for explanation in result.conflict_explanations:
            rules_involved = [s.rule_name or s.rule_id or "unknown" for s in explanation.trace]
            detail = f"No valid values remain for '{explanation.characteristic}'"
            if rules_involved:
                detail += f". Caused by rules: {', '.join(rules_involved)}"
            if explanation.contributing_selections:
                sel_parts = [f"{k}={v}" for k, v in explanation.contributing_selections.items()]
                detail += f". Contributing selections: {', '.join(sel_parts)}"
            errors.append(
                ValidationError(
                    characteristic_slug=explanation.characteristic,
                    error_type="domain_empty",
                    message=detail,
                )
            )

        is_complete = self._check_completeness(char_map, selections, result.auto_set)
        is_valid = len(errors) == 0

        session.available_domains = self._serialize_domains(result.domains)
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

        await db.flush()
        await db.refresh(session, attribute_names=["selections"])
        await db.commit()

        return SelectionResult(
            available_domains=self._serialize_domains(result.domains),
            auto_set_values=result.auto_set,
            excluded_values=result.excluded,
            validation_errors=errors,
            conflict_explanations=result.conflict_explanations,
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
        session = await self._load_session(db, session_id, for_update=True)
        if not session:
            return SelectionResult(
                validation_errors=[ValidationError(error_type="not_found", message="Session not found")]
            )

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

        errors = []
        for explanation in result.conflict_explanations:
            rules_involved = [s.rule_name or s.rule_id or "unknown" for s in explanation.trace]
            detail = f"No valid values remain for '{explanation.characteristic}'"
            if rules_involved:
                detail += f". Caused by rules: {', '.join(rules_involved)}"
            if explanation.contributing_selections:
                sel_parts = [f"{k}={v}" for k, v in explanation.contributing_selections.items()]
                detail += f". Contributing selections: {', '.join(sel_parts)}"
            errors.append(
                ValidationError(
                    characteristic_slug=explanation.characteristic,
                    error_type="domain_empty",
                    message=detail,
                )
            )

        is_complete = self._check_completeness(char_map, selections, result.auto_set)
        is_valid = len(errors) == 0

        session.available_domains = self._serialize_domains(result.domains)
        session.is_valid = is_valid
        session.is_complete = is_complete
        session.validation_errors = [
            {"characteristic_slug": e.characteristic_slug, "error_type": e.error_type, "message": e.message}
            for e in errors
        ]
        session.status = (
            ConfigurationStatus.COMPLETE
            if is_valid and is_complete
            else ConfigurationStatus.INVALID
            if not is_valid
            else ConfigurationStatus.IN_PROGRESS
        )

        await db.flush()
        await db.refresh(session, attribute_names=["selections"])
        await db.commit()

        return SelectionResult(
            available_domains=self._serialize_domains(result.domains),
            auto_set_values=result.auto_set,
            excluded_values=result.excluded,
            validation_errors=errors,
            conflict_explanations=result.conflict_explanations,
            is_valid=is_valid,
            is_complete=is_complete,
        )

    # ── Pure computation ─────────────────────────────────

    def _propagate(
        self,
        domains: DomainMap,
        selections: dict[str, str | list[str]],
        constraints: list,
        variant_tables: dict[str, VariantTable] | dict,
        changed_chars: set[str],
        prebuilt_char_constraints: dict[str, list] | None = None,
    ) -> PropagationResult:
        """Run arc-consistency propagation loop. Pure function, no DB access."""
        propagation_start = _time.monotonic()
        auto_set: dict[str, str] = {}
        excluded: dict[str, list[str]] = defaultdict(list)
        contradictions: list[str] = []
        prune_history: list[DomainPruneRecord] = []

        # Set selected values as single-element domains
        for slug, val in selections.items():
            if slug in domains and not isinstance(val, list):
                if isinstance(domains[slug], NumericInterval):
                    try:
                        fval = float(val)
                        domains[slug] = NumericInterval(min=fval, max=fval)
                    except (ValueError, TypeError):
                        pass
                else:
                    domains[slug] = {val}

        # Build constraint index: char_slug -> [constraints referencing it]
        if prebuilt_char_constraints is not None:
            char_constraints = prebuilt_char_constraints
        else:
            char_constraints: dict[str, list] = defaultdict(list)
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
                rule_id = str(constraint.id) if hasattr(constraint, "id") else None
                rule_name = constraint.name if hasattr(constraint, "name") else None

                if ct == ConstraintType.REQUIRES:
                    if self._evaluate_condition(expr.get("if", {}), selections):
                        then_clause = expr.get("then", {})
                        target_char = then_clause.get("char")
                        if target_char and target_char in domains:
                            target_domain = domains[target_char]
                            # Numeric domain narrowing
                            if isinstance(target_domain, NumericInterval):
                                then_op = then_clause.get("op")
                                then_val = then_clause.get("value")
                                narrowed = target_domain
                                try:
                                    if then_op == "gte" and then_val is not None:
                                        narrowed = target_domain.intersect(NumericInterval(min=float(then_val)))
                                    elif then_op == "lte" and then_val is not None:
                                        narrowed = target_domain.intersect(NumericInterval(max=float(then_val)))
                                    elif then_op == "between" and isinstance(then_val, list) and len(then_val) == 2:
                                        narrowed = target_domain.intersect(
                                            NumericInterval(min=float(then_val[0]), max=float(then_val[1]))
                                        )
                                    elif then_op == "eq" and then_val is not None:
                                        fv = float(then_val)
                                        narrowed = target_domain.intersect(NumericInterval(min=fv, max=fv))
                                except (ValueError, TypeError):
                                    pass
                                if narrowed != target_domain:
                                    prune_history.append(
                                        DomainPruneRecord(
                                            rule_id=rule_id,
                                            rule_name=rule_name,
                                            constraint_type="requires",
                                            target_char=target_char,
                                            removed_values=[
                                                f"narrowed from [{target_domain.min},{target_domain.max}] to [{narrowed.min},{narrowed.max}]"
                                            ],
                                            triggered_by=self._extract_triggering_selections(
                                                expr.get("if", {}), selections
                                            ),
                                        )
                                    )
                                    domains[target_char] = narrowed
                                    queue.add(target_char)
                            else:
                                # Enum/boolean domain pruning
                                required_values = then_clause.get("value")
                                if isinstance(required_values, str):
                                    required_values = [required_values]
                                if required_values:
                                    old = target_domain
                                    new = old & set(required_values)
                                    if new != old:
                                        removed = sorted(old - new)
                                        prune_history.append(
                                            DomainPruneRecord(
                                                rule_id=rule_id,
                                                rule_name=rule_name,
                                                constraint_type="requires",
                                                target_char=target_char,
                                                removed_values=removed,
                                                triggered_by=self._extract_triggering_selections(
                                                    expr.get("if", {}), selections
                                                ),
                                            )
                                        )
                                        domains[target_char] = new
                                        queue.add(target_char)

                elif ct == ConstraintType.EXCLUDES:
                    if self._evaluate_condition(expr.get("if", {}), selections):
                        then_clause = expr.get("then", {})
                        target_char = then_clause.get("char")
                        if target_char and target_char in domains and isinstance(domains[target_char], set):
                            excluded_values = then_clause.get("value")
                            if isinstance(excluded_values, str):
                                excluded_values = [excluded_values]
                            if excluded_values:
                                old = domains[target_char]
                                new = old - set(excluded_values)
                                if new != old:
                                    removed = sorted(old - new)
                                    prune_history.append(
                                        DomainPruneRecord(
                                            rule_id=rule_id,
                                            rule_name=rule_name,
                                            constraint_type="excludes",
                                            target_char=target_char,
                                            removed_values=removed,
                                            triggered_by=self._extract_triggering_selections(
                                                expr.get("if", {}), selections
                                            ),
                                        )
                                    )
                                    excluded[target_char].extend(excluded_values)
                                    domains[target_char] = new
                                    queue.add(target_char)

                elif ct == ConstraintType.SELECTION_CONDITION:
                    condition = expr.get("condition", {})
                    if not self._evaluate_condition(condition, selections):
                        target = expr.get("target", {})
                        target_char = target.get("char")
                        target_value = target.get("value")
                        if (
                            target_char
                            and target_value
                            and target_char in domains
                            and isinstance(domains[target_char], set)
                        ):
                            old = domains[target_char]
                            new = old - {target_value}
                            if new != old:
                                prune_history.append(
                                    DomainPruneRecord(
                                        rule_id=rule_id,
                                        rule_name=rule_name,
                                        constraint_type="selection_condition",
                                        target_char=target_char,
                                        removed_values=[target_value],
                                        triggered_by=self._extract_triggering_selections(condition, selections),
                                    )
                                )
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
                                if isinstance(domains[target_char], NumericInterval):
                                    try:
                                        fv = float(default_val)
                                        domains[target_char] = NumericInterval(min=fv, max=fv)
                                    except (ValueError, TypeError):
                                        pass
                                else:
                                    domains[target_char] = {default_val}
                                queue.add(target_char)

                elif ct == ConstraintType.FORMULA:
                    target_char = expr.get("target")
                    if target_char and target_char in domains and target_char not in selections:
                        computed = self._evaluate_formula(expr, selections)
                        if computed is not None:
                            auto_set[target_char] = computed
                            if isinstance(domains[target_char], NumericInterval):
                                try:
                                    fv = float(computed)
                                    domains[target_char] = NumericInterval(min=fv, max=fv)
                                except (ValueError, TypeError):
                                    pass
                            else:
                                domains[target_char] = {computed}
                            queue.add(target_char)

                elif ct == ConstraintType.TABLE:
                    table_id = expr.get("table_id")
                    if table_id and table_id in variant_tables:
                        vt = variant_tables[table_id]
                        output_values = self._lookup_variant_table(vt, selections)
                        for out_char, out_vals in output_values.items():
                            if out_char in domains and isinstance(domains[out_char], set):
                                old = domains[out_char]
                                new = old & set(out_vals)
                                if new != old:
                                    removed = sorted(old - new)
                                    prune_history.append(
                                        DomainPruneRecord(
                                            rule_id=rule_id,
                                            rule_name=rule_name,
                                            constraint_type="table",
                                            target_char=out_char,
                                            removed_values=removed,
                                            triggered_by=self._extract_triggering_selections(expr, selections),
                                        )
                                    )
                                    domains[out_char] = new
                                    queue.add(out_char)

        # Post-propagation: detect contradictions and auto-set forced values
        conflict_explanations: list[ConflictExplanation] = []
        for slug, domain in domains.items():
            # Handle NumericInterval domains
            if isinstance(domain, NumericInterval):
                if domain.is_empty():
                    contradictions.append(slug)
                    explanation = self._build_conflict_explanation(slug, prune_history, selections)
                    conflict_explanations.append(explanation)
                elif domain.is_single_point() and slug not in selections and slug not in auto_set:
                    auto_set[slug] = str(domain.min)
                continue
            # Handle set[str] domains
            if "__any__" in domain:
                continue
            if len(domain) == 0:
                contradictions.append(slug)
                explanation = self._build_conflict_explanation(slug, prune_history, selections)
                conflict_explanations.append(explanation)
            elif len(domain) == 1 and slug not in selections and slug not in auto_set:
                auto_set[slug] = next(iter(domain))

        # Record metrics
        propagation_elapsed = _time.monotonic() - propagation_start
        CONFIGURATOR_PROPAGATION_DURATION.observe(propagation_elapsed)
        CONFIGURATOR_PROPAGATION_ITERATIONS.observe(iteration)
        if contradictions:
            CONFIGURATOR_CONTRADICTIONS.inc(len(contradictions))

        return PropagationResult(
            domains=domains,
            auto_set=auto_set,
            excluded=dict(excluded),
            contradictions=contradictions,
            prune_history=prune_history,
            conflict_explanations=conflict_explanations,
        )

    def _extract_triggering_selections(self, condition: dict, selections: dict[str, str | list[str]]) -> dict[str, str]:
        """Extract the selection values that caused a condition to fire."""
        triggers: dict[str, str] = {}
        if not condition:
            return triggers
        char_slug = condition.get("char")
        if char_slug and char_slug in selections:
            val = selections[char_slug]
            triggers[char_slug] = val if isinstance(val, str) else ",".join(val) if isinstance(val, list) else str(val)
        for key in ("conditions",):
            if key in condition and isinstance(condition[key], list):
                for sub in condition[key]:
                    if isinstance(sub, dict):
                        triggers.update(self._extract_triggering_selections(sub, selections))
        for key in ("if", "condition"):
            if key in condition and isinstance(condition[key], dict):
                triggers.update(self._extract_triggering_selections(condition[key], selections))
        return triggers

    def _build_conflict_explanation(
        self,
        char_slug: str,
        prune_history: list[DomainPruneRecord],
        selections: dict[str, str | list[str]],
    ) -> ConflictExplanation:
        """Build an explanation of why a characteristic's domain became empty."""
        # Collect all prune records that targeted this characteristic
        trace = [
            ConflictStep(
                rule_id=record.rule_id,
                rule_name=record.rule_name,
                constraint_type=record.constraint_type,
                target_char=record.target_char,
                removed_values=record.removed_values,
                triggered_by=record.triggered_by,
            )
            for record in prune_history
            if record.target_char == char_slug
        ]
        # Collect all user selections that contributed to firing these rules
        contributing: dict[str, str] = {}
        for step in trace:
            contributing.update(step.triggered_by)
        return ConflictExplanation(
            characteristic=char_slug,
            trace=trace,
            contributing_selections=contributing,
        )

    def _evaluate_condition(self, condition: dict, selections: dict[str, str | list[str]]) -> bool:
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
        is_multi = isinstance(current_value, list)

        if op == "eq":
            if is_multi:
                return expected in current_value
            return current_value == expected
        if op == "neq":
            if is_multi:
                return expected not in current_value
            return current_value != expected
        if op == "in":
            if isinstance(expected, list):
                if is_multi:
                    return bool(set(current_value) & set(expected))
                return current_value in expected
            return False
        if op == "not_in":
            if isinstance(expected, list):
                if is_multi:
                    return not bool(set(current_value) & set(expected))
                return current_value not in expected
            return True
        # Numeric operators don't apply to multi-select lists
        if is_multi:
            return False
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
        if op == "between":
            if isinstance(expected, list) and len(expected) == 2:
                try:
                    cv = float(current_value) if isinstance(current_value, str) else current_value
                    return float(expected[0]) <= cv <= float(expected[1])
                except (ValueError, TypeError):
                    return False
            return False

        return True

    def _extract_referenced_chars(self, expression: dict) -> set[str]:
        """Extract all characteristic slugs referenced in an expression."""
        chars = set()
        if "char" in expression:
            chars.add(expression["char"])
        if "target" in expression and isinstance(expression["target"], dict) and "char" in expression["target"]:
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

    # Allowed operators for safe arithmetic evaluation
    _SAFE_OPS: ClassVar[dict[type, object]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    def _safe_eval_ast(self, node: ast.AST, variables: dict[str, float]) -> float:
        """Walk a Python AST allowing only arithmetic on known variables.

        Raises ValueError for any disallowed node type.
        """
        if isinstance(node, ast.Expression):
            return self._safe_eval_ast(node.body, variables)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"Unknown variable: {node.id}")
            return variables[node.id]
        if isinstance(node, ast.BinOp):
            op_func = self._SAFE_OPS.get(type(node.op))
            if op_func is None:
                raise ValueError(f"Disallowed operator: {type(node.op).__name__}")
            left = self._safe_eval_ast(node.left, variables)
            right = self._safe_eval_ast(node.right, variables)
            if isinstance(node.op, ast.Pow):
                if abs(right) > 100:
                    raise ValueError(f"Exponent too large: {right} (max 100)")
                if abs(left) > 1e12:
                    raise ValueError(f"Base too large for exponentiation: {left}")
            return op_func(left, right)
        if isinstance(node, ast.UnaryOp):
            op_func = self._SAFE_OPS.get(type(node.op))
            if op_func is None:
                raise ValueError(f"Disallowed unary operator: {type(node.op).__name__}")
            return op_func(self._safe_eval_ast(node.operand, variables))
        raise ValueError(f"Disallowed AST node: {type(node).__name__}")

    def _evaluate_formula(self, expr: dict, selections: dict[str, str | list[str]]) -> str | None:
        """Evaluate a FORMULA constraint expression.

        Supports two modes:
        1. value_map: {"value_map": {"V8": "250", "I4": "180"}, "input": "engine"}
           Looks up the input char's value in the map.
        2. Safe arithmetic: {"expression": "base + delta", "variables": {"base": "engine_weight", "delta": "option_weight"}}
           Parses expression as AST and evaluates only arithmetic ops on known variables.
        """
        # Mode 1: Value map lookup
        value_map = expr.get("value_map")
        input_char = expr.get("input")
        if value_map and input_char:
            current = selections.get(input_char)
            if current and current in value_map:
                return str(value_map[current])
            return None

        # Mode 2: Safe arithmetic with AST-based evaluation
        formula_str = expr.get("expression")
        variables = expr.get("variables", {})
        if formula_str and variables:
            try:
                local_vars: dict[str, float] = {}
                for var_name, char_slug in variables.items():
                    val = selections.get(char_slug)
                    if val is None:
                        return None
                    try:
                        local_vars[var_name] = float(val)
                    except ValueError:
                        return None
                tree = ast.parse(formula_str, mode="eval")
                result = self._safe_eval_ast(tree, local_vars)
                return str(result)
            except (ValueError, SyntaxError, TypeError, ZeroDivisionError):
                return None

        # Fallback: static value
        return expr.get("value")

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
                    row_val = row.get(col)
                    if row_val is None:
                        match = False
                        break
                    if str(row_val) != str(selections[col]):
                        match = False
                        break
            if match:
                for col in output_cols:
                    val = row.get(col)
                    if val is not None and col in row:
                        output_values[col].append(str(val))

        return dict(output_values)

    # ── Snapshot loading ─────────────────────────────────

    def _load_from_snapshot(
        self, snapshot: dict
    ) -> (
        tuple[
            dict[str, CharacteristicInfo],
            list[SnapshotConstraint],
            dict[str, SnapshotCharacteristic],
            dict[str, list[SnapshotConstraint]],
            DomainMap,
        ]
        | None
    ):
        """Reconstruct product data from a pre-compiled snapshot.

        Returns (char_map, constraints, variant_tables, prebuilt_index, initial_domains)
        or None if the snapshot is incompatible.
        """
        if not snapshot or snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            return None

        # Reconstruct characteristics
        char_map: dict[str, CharacteristicInfo] = {}
        for slug, cdata in snapshot.get("characteristics", {}).items():
            values = [_ValueProxy(v) for v in cdata.get("values", [])]
            snap_char = SnapshotCharacteristic(
                id=cdata["id"],
                slug=slug,
                name=cdata.get("name", slug),
                char_type=_CharTypeProxy(cdata["char_type"]),
                values=values,
                is_required=cdata.get("is_required", False),
                is_multi_select=cdata.get("is_multi_select", False),
                numeric_min=cdata.get("numeric_min"),
                numeric_max=cdata.get("numeric_max"),
                numeric_step=cdata.get("numeric_step"),
                unit=cdata.get("unit"),
                default_value=cdata.get("default_value"),
            )
            char_map[slug] = CharacteristicInfo(
                characteristic=snap_char,
                min_select=cdata.get("min_select"),
                max_select=cdata.get("max_select"),
            )

        # Reconstruct constraints
        constraints: list[SnapshotConstraint] = []
        constraint_by_id: dict[str, SnapshotConstraint] = {}
        for cdata in snapshot.get("constraints", []):
            eff_from = None
            if cdata.get("effective_from"):
                with contextlib.suppress(ValueError, TypeError):
                    eff_from = datetime.fromisoformat(cdata["effective_from"])
            eff_to = None
            if cdata.get("effective_to"):
                with contextlib.suppress(ValueError, TypeError):
                    eff_to = datetime.fromisoformat(cdata["effective_to"])

            sc = SnapshotConstraint(
                id=cdata["id"],
                name=cdata.get("name", ""),
                constraint_type=ConstraintType(cdata["constraint_type"]),
                expression=cdata.get("expression", {}),
                priority=cdata.get("priority", 0),
                is_active=cdata.get("is_active", True),
                effective_from=eff_from,
                effective_to=eff_to,
            )
            constraints.append(sc)
            constraint_by_id[cdata["id"]] = sc

        # Reconstruct variant tables (as dicts — _lookup_variant_table uses .rows, .input_columns, .output_columns)
        variant_tables = {}
        for tid, tdata in snapshot.get("variant_tables", {}).items():

            @dataclass
            class _VTProxy:
                rows: list
                input_columns: list
                output_columns: list

            variant_tables[tid] = _VTProxy(
                rows=tdata.get("rows", []),
                input_columns=tdata.get("input_columns", []),
                output_columns=tdata.get("output_columns", []),
            )

        # Reconstruct prebuilt dependency index
        prebuilt_index: dict[str, list[SnapshotConstraint]] = defaultdict(list)
        for char_slug, rule_ids in snapshot.get("dependency_index", {}).items():
            for rid in rule_ids:
                if rid in constraint_by_id:
                    prebuilt_index[char_slug].append(constraint_by_id[rid])

        # Reconstruct initial domains
        initial_domains: DomainMap = {}
        for slug, dom_data in snapshot.get("initial_domains", {}).items():
            if isinstance(dom_data, dict) and dom_data.get("type") == "numeric":
                initial_domains[slug] = NumericInterval(
                    min=dom_data.get("min"),
                    max=dom_data.get("max"),
                    step=dom_data.get("step"),
                )
            elif isinstance(dom_data, list):
                initial_domains[slug] = set(dom_data)
            else:
                initial_domains[slug] = {"__any__"}

        return char_map, constraints, variant_tables, dict(prebuilt_index), initial_domains

    # ── Helpers ──────────────────────────────────────────

    async def _load_session(
        self, db: AsyncSession, session_id: uuid.UUID, *, for_update: bool = False
    ) -> ConfigurationSession | None:
        stmt = (
            select(ConfigurationSession)
            .where(ConfigurationSession.id == session_id)
            .options(selectinload(ConfigurationSession.selections))
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _load_characteristics(
        self, db: AsyncSession, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> dict[str, CharacteristicInfo]:
        cached = _product_cache.get_chars(product_id, tenant_id)
        if cached is not None:
            return cached
        result = await db.execute(
            select(CharacteristicAssignment)
            .where(CharacteristicAssignment.product_id == product_id, CharacteristicAssignment.tenant_id == tenant_id)
            .options(selectinload(CharacteristicAssignment.characteristic).selectinload(Characteristic.values))
        )
        char_map: dict[str, CharacteristicInfo] = {}
        for assignment in result.scalars().all():
            char = assignment.characteristic
            if char.deleted_at is None:
                char_map[char.slug] = CharacteristicInfo(
                    characteristic=char,
                    min_select=assignment.min_select,
                    max_select=assignment.max_select,
                )
        _product_cache.set_chars(product_id, tenant_id, char_map)
        return char_map

    async def _load_constraints(
        self, db: AsyncSession, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> list[ConstraintRule]:
        cached = _product_cache.get_constraints(product_id, tenant_id)
        if cached is not None:
            return cached
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
        constraints = list(result.scalars().all())
        _product_cache.set_constraints(product_id, tenant_id, constraints)
        return constraints

    async def _load_variant_tables(
        self, db: AsyncSession, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> dict[str, VariantTable]:
        cached = _product_cache.get_vtables(product_id, tenant_id)
        if cached is not None:
            return cached
        result = await db.execute(
            select(VariantTable).where(VariantTable.product_id == product_id, VariantTable.tenant_id == tenant_id)
        )
        vtables = {str(t.id): t for t in result.scalars().all()}
        _product_cache.set_vtables(product_id, tenant_id, vtables)
        return vtables

    def _build_selections_map(
        self,
        selections: list[ConfigurationSelection],
        char_map: dict[str, CharacteristicInfo | Characteristic],
    ) -> dict[str, str | list[str]]:
        """Build {slug: value} from DB selections.

        For multi-select characteristics, builds {slug: [val1, val2, ...]}.
        For single-select, builds {slug: value}.
        """
        id_to_slug = {char.id: slug for slug, char in char_map.items()}
        result: dict[str, str | list[str]] = {}
        for sel in selections:
            slug = id_to_slug.get(sel.characteristic_id)
            if slug:
                char_info = char_map.get(slug)
                if char_info and char_info.is_multi_select:
                    if slug not in result:
                        result[slug] = []
                    result[slug].append(sel.value)
                else:
                    result[slug] = sel.value
        return result

    def _build_initial_domains(self, char_map: dict[str, CharacteristicInfo | Characteristic]) -> DomainMap:
        """Build full (unconstrained) domains from characteristic definitions."""
        domains: DomainMap = {}
        for slug, char in char_map.items():
            if char.char_type.value == "enum":
                domains[slug] = {v.value for v in char.values}
            elif char.char_type.value == "boolean":
                domains[slug] = {"true", "false"}
            elif char.char_type.value == "numeric":
                domains[slug] = NumericInterval(
                    min=char.numeric_min,
                    max=char.numeric_max,
                    step=char.numeric_step,
                )
            else:  # text
                domains[slug] = {"__any__"}
        return domains

    @staticmethod
    def _serialize_domains(domains: DomainMap) -> dict:
        """Serialize domains for JSONB storage / API response.

        NumericInterval -> {"type": "numeric", "min": ..., "max": ..., "step": ...}
        set[str]        -> sorted list of strings
        """
        result = {}
        for k, v in domains.items():
            if isinstance(v, NumericInterval):
                result[k] = v.to_dict()
            else:
                result[k] = sorted(v)
        return result

    def _check_completeness(
        self,
        char_map: dict[str, CharacteristicInfo | Characteristic],
        selections: dict[str, str | list[str]],
        auto_set: dict[str, str],
    ) -> bool:
        """Check if all required characteristics have a selection.

        Also enforces min_select cardinality for multi-select characteristics.
        """
        all_selected = {**selections, **auto_set}
        for slug, char in char_map.items():
            if char.is_required and slug not in all_selected:
                return False
            # Enforce min_select cardinality
            if isinstance(char, CharacteristicInfo) and char.min_select is not None and char.min_select > 0:
                val = all_selected.get(slug)
                if val is None:
                    if char.min_select > 0:
                        return False
                elif isinstance(val, list):
                    if len(val) < char.min_select:
                        return False
                else:
                    # Single value selected; min_select > 1 means incomplete
                    if char.min_select > 1:
                        return False
        return True
