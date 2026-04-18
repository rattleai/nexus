"""Tests for configurator engine, session management, BOM resolution, and pricing."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_tenant, get_db
from app.apps.cpq.engine.engine import ConfiguratorEngine
from app.main import create_app


def _make_tenant():
    return MagicMock(
        id=uuid.uuid4(),
        name="Test",
        slug="test",
        plan="free",
        is_active=True,
    )


def _make_api_key(tenant):
    """Create a mock API key with all scopes for testing authenticated endpoints."""
    api_key = MagicMock()
    api_key.scopes = [
        "products:read",
        "products:write",
        "configurator:read",
        "configurator:write",
    ]
    api_key.tenant = tenant
    return api_key


@pytest.fixture
async def config_client():
    with (
        patch("app.api.v1.health._check_db", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_redis", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_storage", new_callable=AsyncMock, return_value=True),
        patch("app.api.v1.health._check_celery", new_callable=AsyncMock, return_value=True),
        patch("app.core.redis.redis_pool", new_callable=AsyncMock),
    ):
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, app


# ── API Auth Tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_create_session_requires_auth(config_client):
    client, _ = config_client
    response = await client.post(
        "/api/v1/configurator/sessions",
        json={
            "product_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_sessions_requires_auth(config_client):
    client, _ = config_client
    response = await client.get("/api/v1/configurator/sessions")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_session_not_found(config_client):
    client, app = config_client
    tenant = _make_tenant()

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_tenant] = lambda: tenant

    try:
        mock_key = _make_api_key(tenant)
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=mock_key):
            response = await client.get(f"/api/v1/configurator/sessions/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_template_requires_auth(config_client):
    client, _ = config_client
    response = await client.post(
        "/api/v1/configurator/templates",
        json={
            "product_id": str(uuid.uuid4()),
            "name": "Sport Package",
            "selections": [],
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_pricing_rule_requires_auth(config_client):
    client, _ = config_client
    response = await client.post(
        "/api/v1/configurator/pricing/rules",
        json={
            "product_id": str(uuid.uuid4()),
            "name": "Base Price",
            "rule_type": "base_price",
            "expression": {"type": "base_price", "amount": 25000},
        },
    )
    assert response.status_code == 401


# ── Engine Unit Tests (pure logic, no DB) ────────────────


class TestConstraintEvaluation:
    """Test the pure constraint evaluation logic."""

    def setup_method(self):
        self.engine = ConfiguratorEngine()

    def test_evaluate_eq_true(self):
        result = self.engine._evaluate_condition(
            {"char": "engine", "op": "eq", "value": "V8"},
            {"engine": "V8"},
        )
        assert result is True

    def test_evaluate_eq_false(self):
        result = self.engine._evaluate_condition(
            {"char": "engine", "op": "eq", "value": "V8"},
            {"engine": "I4"},
        )
        assert result is False

    def test_evaluate_neq(self):
        result = self.engine._evaluate_condition(
            {"char": "engine", "op": "neq", "value": "V8"},
            {"engine": "I4"},
        )
        assert result is True

    def test_evaluate_in(self):
        result = self.engine._evaluate_condition(
            {"char": "color", "op": "in", "value": ["red", "blue", "green"]},
            {"color": "blue"},
        )
        assert result is True

    def test_evaluate_not_in(self):
        result = self.engine._evaluate_condition(
            {"char": "color", "op": "not_in", "value": ["red", "blue"]},
            {"color": "green"},
        )
        assert result is True

    def test_evaluate_gt(self):
        result = self.engine._evaluate_condition(
            {"char": "weight", "op": "gt", "value": "100"},
            {"weight": "150"},
        )
        assert result is True

    def test_evaluate_lte(self):
        result = self.engine._evaluate_condition(
            {"char": "weight", "op": "lte", "value": "100"},
            {"weight": "100"},
        )
        assert result is True

    def test_evaluate_and(self):
        result = self.engine._evaluate_condition(
            {
                "op": "and",
                "conditions": [
                    {"char": "engine", "op": "eq", "value": "V8"},
                    {"char": "trim", "op": "eq", "value": "sport"},
                ],
            },
            {"engine": "V8", "trim": "sport"},
        )
        assert result is True

    def test_evaluate_and_false(self):
        result = self.engine._evaluate_condition(
            {
                "op": "and",
                "conditions": [
                    {"char": "engine", "op": "eq", "value": "V8"},
                    {"char": "trim", "op": "eq", "value": "sport"},
                ],
            },
            {"engine": "V8", "trim": "base"},
        )
        assert result is False

    def test_evaluate_or(self):
        result = self.engine._evaluate_condition(
            {
                "op": "or",
                "conditions": [
                    {"char": "engine", "op": "eq", "value": "V8"},
                    {"char": "engine", "op": "eq", "value": "V6"},
                ],
            },
            {"engine": "V6"},
        )
        assert result is True

    def test_evaluate_not(self):
        result = self.engine._evaluate_condition(
            {"op": "not", "condition": {"char": "engine", "op": "eq", "value": "V8"}},
            {"engine": "I4"},
        )
        assert result is True

    def test_evaluate_missing_char(self):
        """Unselected characteristics evaluate to False."""
        result = self.engine._evaluate_condition(
            {"char": "engine", "op": "eq", "value": "V8"},
            {},
        )
        assert result is False

    def test_evaluate_empty_condition(self):
        result = self.engine._evaluate_condition({}, {"engine": "V8"})
        assert result is True


class TestConstraintPropagation:
    """Test the propagation algorithm with mock constraints."""

    def setup_method(self):
        self.engine = ConfiguratorEngine()

    def test_requires_propagation(self):
        """REQUIRES: selecting V8 should restrict transmission to auto_6, auto_8."""
        domains = {
            "engine": {"I4", "V6", "V8"},
            "transmission": {"manual_5", "manual_6", "auto_6", "auto_8"},
        }
        selections = {"engine": "V8"}
        domains["engine"] = {"V8"}

        rule = MagicMock()
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        rule.constraint_type = MagicMock(value="requires")
        rule.constraint_type.__eq__ = lambda s, o: s.value == (o.value if hasattr(o, "value") else o)
        from app.apps.cpq.models.product import ConstraintType

        rule.constraint_type = ConstraintType.REQUIRES
        rule.expression = {
            "type": "requires",
            "if": {"char": "engine", "op": "eq", "value": "V8"},
            "then": {"char": "transmission", "op": "in", "value": ["auto_6", "auto_8"]},
        }

        result = self.engine._propagate(domains, selections, [rule], {}, {"engine"})

        assert result.domains["transmission"] == {"auto_6", "auto_8"}
        assert result.contradictions == []

    def test_excludes_propagation(self):
        """EXCLUDES: selecting base trim should exclude panoramic sunroof."""
        domains = {
            "trim": {"base", "sport", "premium"},
            "sunroof": {"none", "standard", "panoramic"},
        }
        selections = {"trim": "base"}
        domains["trim"] = {"base"}

        rule = MagicMock()
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        from app.apps.cpq.models.product import ConstraintType

        rule.constraint_type = ConstraintType.EXCLUDES
        rule.expression = {
            "type": "excludes",
            "if": {"char": "trim", "op": "eq", "value": "base"},
            "then": {"char": "sunroof", "op": "eq", "value": "panoramic"},
        }

        result = self.engine._propagate(domains, selections, [rule], {}, {"trim"})

        assert "panoramic" not in result.domains["sunroof"]
        assert "standard" in result.domains["sunroof"]

    def test_contradiction_detection(self):
        """Empty domain after propagation = contradiction."""
        domains = {
            "engine": {"V8"},
            "transmission": {"manual_5"},
        }
        selections = {"engine": "V8"}

        rule = MagicMock()
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        rule.id = uuid.uuid4()
        rule.name = "V8 requires auto transmission"
        from app.apps.cpq.models.product import ConstraintType

        rule.constraint_type = ConstraintType.REQUIRES
        rule.expression = {
            "type": "requires",
            "if": {"char": "engine", "op": "eq", "value": "V8"},
            "then": {"char": "transmission", "op": "in", "value": ["auto_6", "auto_8"]},
        }

        result = self.engine._propagate(domains, selections, [rule], {}, {"engine"})

        assert "transmission" in result.contradictions

    def test_contradiction_has_conflict_explanation(self):
        """Contradiction should include a conflict explanation trace."""
        domains = {
            "engine": {"V8"},
            "transmission": {"manual_5"},
        }
        selections = {"engine": "V8"}

        rule = MagicMock()
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        rule.id = uuid.uuid4()
        rule.name = "V8 requires auto transmission"
        from app.apps.cpq.models.product import ConstraintType

        rule.constraint_type = ConstraintType.REQUIRES
        rule.expression = {
            "type": "requires",
            "if": {"char": "engine", "op": "eq", "value": "V8"},
            "then": {"char": "transmission", "op": "in", "value": ["auto_6", "auto_8"]},
        }

        result = self.engine._propagate(domains, selections, [rule], {}, {"engine"})

        assert len(result.conflict_explanations) == 1
        explanation = result.conflict_explanations[0]
        assert explanation.characteristic == "transmission"
        assert len(explanation.trace) >= 1
        assert explanation.trace[0].rule_name == "V8 requires auto transmission"
        assert explanation.trace[0].constraint_type == "requires"
        assert "manual_5" in explanation.trace[0].removed_values
        assert explanation.contributing_selections.get("engine") == "V8"

    def test_prune_history_tracks_excludes(self):
        """Prune history should record which values were removed by EXCLUDES."""
        domains = {
            "trim": {"base"},
            "sunroof": {"none", "standard", "panoramic"},
        }
        selections = {"trim": "base"}

        rule = MagicMock()
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        rule.id = uuid.uuid4()
        rule.name = "Base trim excludes panoramic"
        from app.apps.cpq.models.product import ConstraintType

        rule.constraint_type = ConstraintType.EXCLUDES
        rule.expression = {
            "type": "excludes",
            "if": {"char": "trim", "op": "eq", "value": "base"},
            "then": {"char": "sunroof", "op": "eq", "value": "panoramic"},
        }

        result = self.engine._propagate(domains, selections, [rule], {}, {"trim"})

        assert len(result.prune_history) >= 1
        prune = result.prune_history[0]
        assert prune.target_char == "sunroof"
        assert "panoramic" in prune.removed_values
        assert prune.triggered_by.get("trim") == "base"

    def test_auto_set_single_value_domain(self):
        """When domain has exactly one value left, it should be auto-set."""
        domains = {
            "engine": {"V8"},
            "fuel": {"gasoline", "diesel"},
        }
        selections = {"engine": "V8"}

        rule = MagicMock()
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        from app.apps.cpq.models.product import ConstraintType

        rule.constraint_type = ConstraintType.REQUIRES
        rule.expression = {
            "type": "requires",
            "if": {"char": "engine", "op": "eq", "value": "V8"},
            "then": {"char": "fuel", "op": "in", "value": ["gasoline"]},
        }

        result = self.engine._propagate(domains, selections, [rule], {}, {"engine"})

        assert result.auto_set.get("fuel") == "gasoline"

    def test_selection_condition_propagation(self):
        """SELECTION_CONDITION: 20" wheels only available with sport suspension."""
        domains = {
            "suspension": {"standard", "sport"},
            "wheel_size": {"17_inch", "18_inch", "20_inch"},
        }
        selections = {"suspension": "standard"}
        domains["suspension"] = {"standard"}

        rule = MagicMock()
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        from app.apps.cpq.models.product import ConstraintType

        rule.constraint_type = ConstraintType.SELECTION_CONDITION
        rule.expression = {
            "type": "selection_condition",
            "target": {"char": "wheel_size", "value": "20_inch"},
            "condition": {"char": "suspension", "op": "eq", "value": "sport"},
        }

        result = self.engine._propagate(domains, selections, [rule], {}, {"suspension"})

        assert "20_inch" not in result.domains["wheel_size"]
        assert "17_inch" in result.domains["wheel_size"]
        assert "18_inch" in result.domains["wheel_size"]


class TestExtractReferencedChars:
    """Test the helper that extracts characteristic slugs from expressions."""

    def setup_method(self):
        self.engine = ConfiguratorEngine()

    def test_simple_requires(self):
        expr = {
            "if": {"char": "engine", "op": "eq", "value": "V8"},
            "then": {"char": "transmission", "op": "in", "value": ["auto"]},
        }
        result = self.engine._extract_referenced_chars(expr)
        assert result == {"engine", "transmission"}

    def test_compound_and(self):
        expr = {
            "if": {
                "op": "and",
                "conditions": [
                    {"char": "a", "op": "eq", "value": "1"},
                    {"char": "b", "op": "eq", "value": "2"},
                ],
            },
            "then": {"char": "c", "op": "eq", "value": "3"},
        }
        result = self.engine._extract_referenced_chars(expr)
        assert result == {"a", "b", "c"}

    def test_selection_condition(self):
        expr = {
            "target": {"char": "wheel_size", "value": "20_inch"},
            "condition": {"char": "suspension", "op": "eq", "value": "sport"},
        }
        result = self.engine._extract_referenced_chars(expr)
        assert result == {"wheel_size", "suspension"}


class TestFormulaEvaluation:
    """Test the safe AST-based formula evaluator."""

    def setup_method(self):
        self.engine = ConfiguratorEngine()

    def test_value_map_lookup(self):
        expr = {"target": "hp", "value_map": {"V8": "450", "I4": "180"}, "input": "engine"}
        result = self.engine._evaluate_formula(expr, {"engine": "V8"})
        assert result == "450"

    def test_value_map_missing_input(self):
        expr = {"target": "hp", "value_map": {"V8": "450"}, "input": "engine"}
        result = self.engine._evaluate_formula(expr, {})
        assert result is None

    def test_simple_addition(self):
        expr = {"target": "total", "expression": "a + b", "variables": {"a": "weight", "b": "cargo"}}
        result = self.engine._evaluate_formula(expr, {"weight": "100", "cargo": "50"})
        assert result == "150.0"

    def test_complex_arithmetic(self):
        expr = {
            "target": "cost",
            "expression": "base * qty + shipping",
            "variables": {"base": "unit_price", "qty": "quantity", "shipping": "ship_cost"},
        }
        result = self.engine._evaluate_formula(expr, {"unit_price": "10", "quantity": "5", "ship_cost": "7.5"})
        assert result == "57.5"

    def test_division(self):
        expr = {"target": "ratio", "expression": "a / b", "variables": {"a": "top", "b": "bottom"}}
        result = self.engine._evaluate_formula(expr, {"top": "100", "bottom": "4"})
        assert result == "25.0"

    def test_power(self):
        expr = {"target": "area", "expression": "side ** 2", "variables": {"side": "length"}}
        result = self.engine._evaluate_formula(expr, {"length": "5"})
        assert result == "25.0"

    def test_negation(self):
        expr = {"target": "neg", "expression": "-a", "variables": {"a": "val"}}
        result = self.engine._evaluate_formula(expr, {"val": "42"})
        assert result == "-42.0"

    def test_missing_variable_returns_none(self):
        expr = {"target": "x", "expression": "a + b", "variables": {"a": "x", "b": "y"}}
        result = self.engine._evaluate_formula(expr, {"x": "10"})
        assert result is None

    def test_non_numeric_variable_returns_none(self):
        expr = {"target": "x", "expression": "a + b", "variables": {"a": "x", "b": "y"}}
        result = self.engine._evaluate_formula(expr, {"x": "10", "y": "abc"})
        assert result is None

    def test_division_by_zero_returns_none(self):
        expr = {"target": "x", "expression": "a / b", "variables": {"a": "x", "b": "y"}}
        result = self.engine._evaluate_formula(expr, {"x": "10", "y": "0"})
        assert result is None

    def test_rejects_function_calls(self):
        """Ensure function call expressions are rejected by the safe evaluator."""
        # Construct a string that attempts to call a builtin function
        dangerous = "".join(["__imp", "ort__('os')"])
        expr = {"target": "x", "expression": dangerous, "variables": {}}
        result = self.engine._evaluate_formula(expr, {})
        assert result is None

    def test_rejects_attribute_access(self):
        """Ensure attribute access chains are rejected by the safe evaluator."""
        expr = {"target": "x", "expression": "a.__class__", "variables": {"a": "val"}}
        result = self.engine._evaluate_formula(expr, {"val": "1"})
        assert result is None

    def test_rejects_list_comprehension(self):
        expr = {"target": "x", "expression": "[x for x in range(10)]", "variables": {}}
        result = self.engine._evaluate_formula(expr, {})
        assert result is None

    def test_static_value_fallback(self):
        expr = {"target": "x", "value": "42"}
        result = self.engine._evaluate_formula(expr, {})
        assert result == "42"

    def test_syntax_error_returns_none(self):
        expr = {"target": "x", "expression": "a +", "variables": {"a": "val"}}
        result = self.engine._evaluate_formula(expr, {"val": "1"})
        assert result is None
