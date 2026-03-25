"""Tests for configurator engine, session management, BOM resolution, and pricing."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_tenant, get_db
from app.configurator.engine import ConfiguratorEngine, SelectionResult
from app.main import create_app


def _make_tenant():
    return MagicMock(
        id=uuid.uuid4(), name="Test", slug="test", plan="free", is_active=True,
    )


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
    response = await client.post("/api/v1/configurator/sessions", json={
        "product_id": str(uuid.uuid4()),
    })
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
        with patch("app.api.deps._resolve_api_key", new_callable=AsyncMock, return_value=None):
            response = await client.get(f"/api/v1/configurator/sessions/{uuid.uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_template_requires_auth(config_client):
    client, _ = config_client
    response = await client.post("/api/v1/configurator/templates", json={
        "product_id": str(uuid.uuid4()),
        "name": "Sport Package",
        "selections": [],
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_pricing_rule_requires_auth(config_client):
    client, _ = config_client
    response = await client.post("/api/v1/configurator/pricing/rules", json={
        "product_id": str(uuid.uuid4()),
        "name": "Base Price",
        "rule_type": "base_price",
        "expression": {"type": "base_price", "amount": 25000},
    })
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
            {"op": "and", "conditions": [
                {"char": "engine", "op": "eq", "value": "V8"},
                {"char": "trim", "op": "eq", "value": "sport"},
            ]},
            {"engine": "V8", "trim": "sport"},
        )
        assert result is True

    def test_evaluate_and_false(self):
        result = self.engine._evaluate_condition(
            {"op": "and", "conditions": [
                {"char": "engine", "op": "eq", "value": "V8"},
                {"char": "trim", "op": "eq", "value": "sport"},
            ]},
            {"engine": "V8", "trim": "base"},
        )
        assert result is False

    def test_evaluate_or(self):
        result = self.engine._evaluate_condition(
            {"op": "or", "conditions": [
                {"char": "engine", "op": "eq", "value": "V8"},
                {"char": "engine", "op": "eq", "value": "V6"},
            ]},
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
        rule.constraint_type.__eq__ = lambda s, o: s.value == (o.value if hasattr(o, 'value') else o)
        from app.db.models import ConstraintType
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
        from app.db.models import ConstraintType
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
        from app.db.models import ConstraintType
        rule.constraint_type = ConstraintType.REQUIRES
        rule.expression = {
            "type": "requires",
            "if": {"char": "engine", "op": "eq", "value": "V8"},
            "then": {"char": "transmission", "op": "in", "value": ["auto_6", "auto_8"]},
        }

        result = self.engine._propagate(domains, selections, [rule], {}, {"engine"})

        assert "transmission" in result.contradictions

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
        from app.db.models import ConstraintType
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
        from app.db.models import ConstraintType
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
            "if": {"op": "and", "conditions": [
                {"char": "a", "op": "eq", "value": "1"},
                {"char": "b", "op": "eq", "value": "2"},
            ]},
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
