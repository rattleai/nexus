"""Configuration validation — completeness and constraint satisfaction checks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.apps.cpq.engine.engine import ConfiguratorEngine, ValidationError
from app.apps.cpq.models.configurator import ConfigurationSession
from app.apps.cpq.models.product import (
    Characteristic,
    CharacteristicAssignment,
)

logger = structlog.stdlib.get_logger()


@dataclass
class ValidationResult:
    is_valid: bool = False
    is_complete: bool = False
    errors: list[ValidationError] = field(default_factory=list)


@dataclass
class CompletenessResult:
    is_complete: bool = False
    missing_required: list[str] = field(default_factory=list)


class ConfigurationValidator:
    """Validates a configuration session for completeness and consistency."""

    def __init__(self):
        self._engine = ConfiguratorEngine()

    async def validate(self, db: AsyncSession, session_id: uuid.UUID) -> ValidationResult:
        """Run full validation including constraint propagation."""
        session = await self._engine._load_session(db, session_id)
        if not session:
            return ValidationResult(errors=[ValidationError(error_type="not_found", message="Session not found")])

        char_map = await self._engine._load_characteristics(db, session.product_id, session.tenant_id)
        constraints = await self._engine._load_constraints(db, session.product_id, session.tenant_id)
        variant_tables = await self._engine._load_variant_tables(db, session.product_id, session.tenant_id)

        selections = self._engine._build_selections_map(session.selections, char_map)
        domains = self._engine._build_initial_domains(char_map)

        result = self._engine._propagate(domains, selections, constraints, variant_tables, set(selections.keys()))

        errors: list[ValidationError] = []

        # Contradiction errors
        for c in result.contradictions:
            errors.append(ValidationError(
                characteristic_slug=c,
                error_type="domain_empty",
                message=f"No valid values remain for '{c}'",
            ))

        # Required but missing
        all_selected = {**selections, **result.auto_set}
        for slug, char in char_map.items():
            if char.is_required and slug not in all_selected:
                errors.append(ValidationError(
                    characteristic_slug=slug,
                    error_type="required_missing",
                    message=f"Required characteristic '{slug}' has no value",
                ))

        # Domain validity (enum value must be in allowed set)
        for slug, value in selections.items():
            if slug in char_map:
                char = char_map[slug]
                if char.char_type.value == "enum":
                    allowed = {v.value for v in char.values}
                    if value not in allowed:
                        errors.append(ValidationError(
                            characteristic_slug=slug,
                            error_type="invalid_value",
                            message=f"Value '{value}' is not a valid option for '{slug}'",
                        ))

        is_complete = self._engine._check_completeness(char_map, selections, result.auto_set)
        is_valid = len(errors) == 0

        return ValidationResult(is_valid=is_valid, is_complete=is_complete, errors=errors)

    async def check_completeness(self, db: AsyncSession, session_id: uuid.UUID) -> CompletenessResult:
        """Lightweight check: are all required fields filled?"""
        session = await self._engine._load_session(db, session_id)
        if not session:
            return CompletenessResult()

        char_map = await self._engine._load_characteristics(db, session.product_id, session.tenant_id)
        selections = self._engine._build_selections_map(session.selections, char_map)

        missing = []
        for slug, char in char_map.items():
            if char.is_required and slug not in selections:
                missing.append(slug)

        return CompletenessResult(is_complete=len(missing) == 0, missing_required=missing)
