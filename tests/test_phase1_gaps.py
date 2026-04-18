"""Comprehensive tests for Phase 1 gap implementations.

Tests cover: P1.1 (numeric domains), P1.2 (quantity expressions), P1.3 (tiered pricing),
P1.4 (constraint analysis), P1.5 (N+1 fixes), P1.7 (simulation), P1.8 (cardinality).
"""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.apps.cpq.engine.analyzer import ConstraintAnalyzer
from app.apps.cpq.engine.bom_resolver import BOMResolver, ResolvedItem
from app.apps.cpq.engine.engine import (
    CharacteristicInfo,
    ConfiguratorEngine,
    NumericInterval,
)

# ── P1.1: NumericInterval Tests ──────────────────────────


class TestNumericInterval:
    def test_unbounded_is_not_empty(self):
        ni = NumericInterval()
        assert not ni.is_empty()
        assert not ni.is_single_point()

    def test_bounded_interval(self):
        ni = NumericInterval(min=0, max=100)
        assert not ni.is_empty()
        assert not ni.is_single_point()

    def test_single_point(self):
        ni = NumericInterval(min=42.0, max=42.0)
        assert ni.is_single_point()
        assert not ni.is_empty()

    def test_empty_interval(self):
        ni = NumericInterval(min=100, max=0)
        assert ni.is_empty()

    def test_intersect_overlapping(self):
        a = NumericInterval(min=0, max=100)
        b = NumericInterval(min=50, max=200)
        result = a.intersect(b)
        assert result.min == 50
        assert result.max == 100

    def test_intersect_disjoint_is_empty(self):
        a = NumericInterval(min=0, max=10)
        b = NumericInterval(min=20, max=30)
        result = a.intersect(b)
        assert result.is_empty()

    def test_intersect_with_unbounded(self):
        a = NumericInterval(min=0, max=100)
        b = NumericInterval(min=50)  # unbounded above
        result = a.intersect(b)
        assert result.min == 50
        assert result.max == 100

    def test_intersect_to_single_point(self):
        a = NumericInterval(min=0, max=50)
        b = NumericInterval(min=50, max=100)
        result = a.intersect(b)
        assert result.is_single_point()
        assert result.min == 50

    def test_contains_value(self):
        ni = NumericInterval(min=0, max=100)
        assert ni.contains(50)
        assert ni.contains(0)
        assert ni.contains(100)
        assert not ni.contains(-1)
        assert not ni.contains(101)

    def test_contains_with_step(self):
        ni = NumericInterval(min=0, max=100, step=10)
        assert ni.contains(0)
        assert ni.contains(10)
        assert ni.contains(50)
        assert not ni.contains(15)

    def test_to_dict(self):
        ni = NumericInterval(min=0, max=100, step=5)
        d = ni.to_dict()
        assert d == {"type": "numeric", "min": 0, "max": 100, "step": 5}

    def test_frozen(self):
        ni = NumericInterval(min=0, max=100)
        with pytest.raises(AttributeError):
            ni.min = 50


# ── P1.1: Between Operator ──────────────────────────────


class TestBetweenOperator:
    def setup_method(self):
        self.engine = ConfiguratorEngine()

    def test_between_true(self):
        result = self.engine._evaluate_condition(
            {"char": "weight", "op": "between", "value": [100, 500]},
            {"weight": "250"},
        )
        assert result is True

    def test_between_false_below(self):
        result = self.engine._evaluate_condition(
            {"char": "weight", "op": "between", "value": [100, 500]},
            {"weight": "50"},
        )
        assert result is False

    def test_between_false_above(self):
        result = self.engine._evaluate_condition(
            {"char": "weight", "op": "between", "value": [100, 500]},
            {"weight": "600"},
        )
        assert result is False

    def test_between_boundary_inclusive(self):
        assert (
            self.engine._evaluate_condition(
                {"char": "x", "op": "between", "value": [10, 20]},
                {"x": "10"},
            )
            is True
        )
        assert (
            self.engine._evaluate_condition(
                {"char": "x", "op": "between", "value": [10, 20]},
                {"x": "20"},
            )
            is True
        )

    def test_between_missing_char(self):
        result = self.engine._evaluate_condition(
            {"char": "weight", "op": "between", "value": [100, 500]},
            {},
        )
        assert result is False


# ── P1.1: Numeric Domain Propagation ────────────────────


class TestNumericDomainPropagation:
    def setup_method(self):
        self.engine = ConfiguratorEngine()

    def _make_constraint(self, ct, expression):
        rule = MagicMock()
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        rule.constraint_type = ct
        rule.expression = expression
        rule.id = uuid.uuid4()
        rule.name = "test_rule"
        return rule

    def test_numeric_domain_initial(self):
        char = MagicMock()
        char.char_type.value = "numeric"
        char.numeric_min = 0.0
        char.numeric_max = 100.0
        char.numeric_step = None
        char.values = []
        char.is_required = False
        char.is_multi_select = False
        char_info = CharacteristicInfo(characteristic=char)
        domains = self.engine._build_initial_domains({"weight": char_info})
        assert isinstance(domains["weight"], NumericInterval)
        assert domains["weight"].min == 0.0
        assert domains["weight"].max == 100.0

    def test_numeric_selection_sets_point(self):
        domains = {"weight": NumericInterval(min=0, max=100)}
        result = self.engine._propagate(domains, {"weight": "42"}, [], {}, {"weight"})
        d = result.domains["weight"]
        assert isinstance(d, NumericInterval)
        assert d.is_single_point()
        assert d.min == 42.0

    def test_numeric_requires_narrows_interval(self):
        from app.apps.cpq.models.product import ConstraintType

        rule = self._make_constraint(
            ConstraintType.REQUIRES,
            {
                "if": {"char": "engine", "op": "eq", "value": "V8"},
                "then": {"char": "weight", "op": "gte", "value": 200},
            },
        )
        domains = {
            "engine": {"V8", "V6"},
            "weight": NumericInterval(min=0, max=500),
        }
        result = self.engine._propagate(domains, {"engine": "V8"}, [rule], {}, {"engine"})
        d = result.domains["weight"]
        assert isinstance(d, NumericInterval)
        assert d.min == 200
        assert d.max == 500

    def test_numeric_contradiction(self):
        from app.apps.cpq.models.product import ConstraintType

        rule1 = self._make_constraint(
            ConstraintType.REQUIRES,
            {
                "if": {"char": "mode", "op": "eq", "value": "A"},
                "then": {"char": "val", "op": "gte", "value": 100},
            },
        )
        rule2 = self._make_constraint(
            ConstraintType.REQUIRES,
            {
                "if": {"char": "mode", "op": "eq", "value": "A"},
                "then": {"char": "val", "op": "lte", "value": 50},
            },
        )
        domains = {
            "mode": {"A", "B"},
            "val": NumericInterval(min=0, max=500),
        }
        result = self.engine._propagate(domains, {"mode": "A"}, [rule1, rule2], {}, {"mode"})
        assert "val" in result.contradictions

    def test_serialize_numeric_domains(self):
        domains = {
            "color": {"red", "blue"},
            "weight": NumericInterval(min=0, max=100, step=5),
        }
        s = ConfiguratorEngine._serialize_domains(domains)
        assert isinstance(s["color"], list)
        assert s["weight"] == {"type": "numeric", "min": 0, "max": 100, "step": 5}

    def test_enum_domains_unchanged(self):
        char = MagicMock()
        char.char_type.value = "enum"
        val1 = MagicMock()
        val1.value = "red"
        val2 = MagicMock()
        val2.value = "blue"
        char.values = [val1, val2]
        char.is_required = False
        char.is_multi_select = False
        char_info = CharacteristicInfo(characteristic=char)
        domains = self.engine._build_initial_domains({"color": char_info})
        assert isinstance(domains["color"], set)
        assert domains["color"] == {"red", "blue"}


# ── P1.2: Quantity Expression Tests ─────────────────────


class TestQuantityExpressions:
    def setup_method(self):
        self.resolver = BOMResolver()

    def _item(self, qty=Decimal("1"), expr=None):
        return ResolvedItem(
            part_number="P001",
            part_name="Part",
            quantity=qty,
            unit="EA",
            unit_cost=Decimal("10"),
            level=0,
            parent_part=None,
            source_bom_item_id="bom1",
            item_type="component",
            quantity_expression=expr,
        )

    def test_no_expression_keeps_fixed(self):
        item = self._item(qty=Decimal("5"))
        result = self.resolver._resolve_quantities([item], {})
        assert result[0].quantity == Decimal("5")

    def test_simple_formula(self):
        item = self._item(
            expr={
                "type": "formula",
                "expression": "count * 2",
                "variables": {"count": "panel_count"},
            }
        )
        result = self.resolver._resolve_quantities([item], {"panel_count": "5"})
        assert result[0].quantity == Decimal("10.0000")

    def test_formula_with_addition(self):
        item = self._item(
            expr={
                "type": "formula",
                "expression": "count * 2 + 1",
                "variables": {"count": "panel_count"},
            }
        )
        result = self.resolver._resolve_quantities([item], {"panel_count": "3"})
        assert result[0].quantity == Decimal("7.0000")

    def test_missing_variable_keeps_fixed(self):
        item = self._item(
            qty=Decimal("5"),
            expr={
                "type": "formula",
                "expression": "count * 2",
                "variables": {"count": "missing_char"},
            },
        )
        result = self.resolver._resolve_quantities([item], {})
        assert result[0].quantity == Decimal("5")

    def test_division_by_zero_keeps_fixed(self):
        item = self._item(
            qty=Decimal("5"),
            expr={
                "type": "formula",
                "expression": "count / zero",
                "variables": {"count": "a", "zero": "b"},
            },
        )
        result = self.resolver._resolve_quantities([item], {"a": "10", "b": "0"})
        assert result[0].quantity == Decimal("5")

    def test_negative_result_keeps_fixed(self):
        item = self._item(
            qty=Decimal("5"),
            expr={
                "type": "formula",
                "expression": "count - 100",
                "variables": {"count": "a"},
            },
        )
        result = self.resolver._resolve_quantities([item], {"a": "1"})
        assert result[0].quantity == Decimal("5")

    def test_clamp_min_max(self):
        item = self._item(
            expr={
                "type": "formula",
                "expression": "count * 100",
                "variables": {"count": "a"},
                "min": 1,
                "max": 50,
            }
        )
        result = self.resolver._resolve_quantities([item], {"a": "10"})
        assert result[0].quantity == Decimal("50.0000")

    def test_non_formula_type_ignored(self):
        item = self._item(qty=Decimal("5"), expr={"type": "table"})
        result = self.resolver._resolve_quantities([item], {})
        assert result[0].quantity == Decimal("5")


# ── P1.3: Tiered Pricing Tests ──────────────────────────


class TestTieredPricing:
    def setup_method(self):
        self.resolver = BOMResolver()

    def test_all_units_single_tier(self):
        tiers = [{"min": 0, "max": None, "price": "100"}]
        result = self.resolver._calculate_tiered_price_all_units(Decimal("25"), tiers)
        assert result == Decimal("2500")

    def test_all_units_falls_in_tier_2(self):
        tiers = [
            {"min": 0, "max": 10, "price": "100"},
            {"min": 11, "max": 50, "price": "90"},
            {"min": 51, "max": None, "price": "75"},
        ]
        result = self.resolver._calculate_tiered_price_all_units(Decimal("25"), tiers)
        assert result == Decimal("2250")  # 25 * 90

    def test_all_units_exceeds_all_tiers(self):
        tiers = [
            {"min": 0, "max": 10, "price": "100"},
            {"min": 11, "max": 50, "price": "90"},
        ]
        result = self.resolver._calculate_tiered_price_all_units(Decimal("100"), tiers)
        assert result == Decimal("9000")  # 100 * 90 (last tier)

    def test_marginal_multi_tier(self):
        tiers = [
            {"min": 0, "max": 10, "price": "100"},
            {"min": 11, "max": 50, "price": "90"},
        ]
        # 11 units at $100 + 14 units at $90 = 1100 + 1260 = 2360
        result = self.resolver._calculate_tiered_price_marginal(Decimal("25"), tiers)
        assert result == Decimal("2360")

    def test_marginal_exceeds_all_tiers(self):
        tiers = [
            {"min": 0, "max": 10, "price": "100"},
            {"min": 11, "max": 20, "price": "90"},
        ]
        # 11 at 100 + 10 at 90 + remaining 69 at 90 (last tier) = 1100 + 900 = 2000
        result = self.resolver._calculate_tiered_price_marginal(Decimal("21"), tiers)
        # 11 * 100 = 1100, then 10 * 90 = 900, total = 2000
        assert result == Decimal("2000")

    def test_quantity_zero(self):
        tiers = [{"min": 0, "max": None, "price": "100"}]
        all_units = self.resolver._calculate_tiered_price_all_units(Decimal("0"), tiers)
        marginal = self.resolver._calculate_tiered_price_marginal(Decimal("0"), tiers)
        assert all_units == Decimal("0")
        assert marginal == Decimal("0")

    def test_empty_tiers(self):
        result = self.resolver._calculate_tiered_price_all_units(Decimal("10"), [])
        assert result == Decimal("0")

    def test_find_matching_tier(self):
        tiers = [
            {"min": 0, "max": 10, "price": "100"},
            {"min": 11, "max": None, "price": "90"},
        ]
        match = self.resolver._find_matching_tier(Decimal("5"), tiers)
        assert match is not None
        assert match["price"] == "100"
        match2 = self.resolver._find_matching_tier(Decimal("15"), tiers)
        assert match2["price"] == "90"


# ── P1.4: Constraint Analyzer Tests ─────────────────────


class TestConstraintAnalyzer:
    def setup_method(self):
        self.analyzer = ConstraintAnalyzer()

    def _mock_char(self, slug, char_type="enum", values=None, is_required=False):
        char = MagicMock()
        char.id = uuid.uuid4()
        char.slug = slug
        char.char_type.value = char_type
        if values:
            char.values = [MagicMock(value=v) for v in values]
        else:
            char.values = []
        char.is_required = is_required
        char.is_multi_select = False
        char.numeric_min = None
        char.numeric_max = None
        char.numeric_step = None
        char.default_value = None
        char.deleted_at = None
        return CharacteristicInfo(characteristic=char)

    def _mock_rule(self, ct_str, expression):
        from app.apps.cpq.models.product import ConstraintType

        rule = MagicMock()
        rule.id = uuid.uuid4()
        rule.name = f"rule_{ct_str}"
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        rule.constraint_type = ConstraintType(ct_str)
        rule.expression = expression
        return rule

    def test_no_cycles(self):
        char_map = {
            "a": self._mock_char("a", values=["1", "2"]),
            "b": self._mock_char("b", values=["x", "y"]),
        }
        rule = self._mock_rule(
            "requires",
            {
                "if": {"char": "a", "op": "eq", "value": "1"},
                "then": {"char": "b", "value": "x"},
            },
        )
        result = self.analyzer.analyze(char_map, [rule], {})
        assert len(result.cycles) == 0

    def test_simple_cycle(self):
        char_map = {
            "a": self._mock_char("a", values=["1", "2"]),
            "b": self._mock_char("b", values=["x", "y"]),
        }
        rule1 = self._mock_rule(
            "requires",
            {
                "if": {"char": "a", "op": "eq", "value": "1"},
                "then": {"char": "b", "value": "x"},
            },
        )
        rule2 = self._mock_rule(
            "requires",
            {
                "if": {"char": "b", "op": "eq", "value": "x"},
                "then": {"char": "a", "value": "1"},
            },
        )
        result = self.analyzer.analyze(char_map, [rule1, rule2], {})
        assert len(result.cycles) > 0

    def test_dead_value_unconditional(self):
        char_map = {
            "color": self._mock_char("color", values=["red", "blue", "green"]),
        }
        rule = self._mock_rule(
            "excludes",
            {
                "if": {},
                "then": {"char": "color", "value": "red"},
            },
        )
        result = self.analyzer.analyze(char_map, [rule], {})
        dead_vals = [d.value for d in result.dead_values]
        assert "red" in dead_vals

    def test_coverage_gap(self):
        char_map = {
            "engine": self._mock_char("engine", values=["V6", "V8"], is_required=True),
        }
        result = self.analyzer.analyze(char_map, [], {})
        assert len(result.coverage_gaps) > 0
        assert result.coverage_gaps[0].characteristic == "engine"

    def test_satisfiable(self):
        char_map = {
            "a": self._mock_char("a", values=["1", "2"]),
        }
        result = self.analyzer.analyze(char_map, [], {})
        assert result.is_satisfiable is True

    def test_has_duration(self):
        result = self.analyzer.analyze({}, [], {})
        assert result.analysis_duration_ms >= 0


# ── P1.8: Cardinality Tests ─────────────────────────────


class TestCardinality:
    def setup_method(self):
        self.engine = ConfiguratorEngine()

    def test_characteristic_info_delegation(self):
        char = MagicMock()
        char.char_type.value = "enum"
        char.slug = "color"
        char.is_required = True
        info = CharacteristicInfo(characteristic=char, min_select=2, max_select=5)
        assert info.slug == "color"
        assert info.is_required is True
        assert info.min_select == 2
        assert info.max_select == 5

    def test_check_completeness_min_select(self):
        char = MagicMock()
        char.char_type.value = "enum"
        char.is_required = False
        char.is_multi_select = True
        char.values = []
        info = CharacteristicInfo(characteristic=char, min_select=2, max_select=5)
        # Only 1 selection, min is 2
        assert self.engine._check_completeness({"color": info}, {"color": "red"}, {}) is False

    def test_check_completeness_min_met(self):
        char = MagicMock()
        char.char_type.value = "enum"
        char.is_required = False
        char.is_multi_select = True
        char.values = []
        info = CharacteristicInfo(characteristic=char, min_select=2, max_select=5)
        assert self.engine._check_completeness({"color": info}, {"color": ["red", "blue"]}, {}) is True

    def test_null_cardinality_unconstrained(self):
        char = MagicMock()
        char.char_type.value = "enum"
        char.is_required = False
        char.is_multi_select = True
        char.values = []
        info = CharacteristicInfo(characteristic=char, min_select=None, max_select=None)
        assert self.engine._check_completeness({"color": info}, {"color": "red"}, {}) is True

    def test_multi_select_builds_list(self):
        char = MagicMock()
        char.id = uuid.uuid4()
        char.char_type.value = "enum"
        char.is_multi_select = True
        info = CharacteristicInfo(characteristic=char)

        sel1 = MagicMock()
        sel1.characteristic_id = char.id
        sel1.value = "red"
        sel2 = MagicMock()
        sel2.characteristic_id = char.id
        sel2.value = "blue"

        result = self.engine._build_selections_map([sel1, sel2], {"color": info})
        assert isinstance(result["color"], list)
        assert "red" in result["color"]
        assert "blue" in result["color"]


# ── P1.6: Snapshot Tests ────────────────────────────────


class TestSnapshotLoading:
    def setup_method(self):
        self.engine = ConfiguratorEngine()

    def test_load_from_incompatible_snapshot(self):
        result = self.engine._load_from_snapshot({"schema_version": 999})
        assert result is None

    def test_load_from_empty_snapshot(self):
        result = self.engine._load_from_snapshot({})
        assert result is None

    def test_load_from_valid_snapshot(self):
        snapshot = {
            "schema_version": 1,
            "characteristics": {
                "color": {
                    "id": str(uuid.uuid4()),
                    "name": "Color",
                    "slug": "color",
                    "char_type": "enum",
                    "values": ["red", "blue"],
                    "is_required": True,
                    "is_multi_select": False,
                    "numeric_min": None,
                    "numeric_max": None,
                },
            },
            "constraints": [
                {
                    "id": str(uuid.uuid4()),
                    "name": "test",
                    "constraint_type": "requires",
                    "expression": {
                        "if": {"char": "color", "op": "eq", "value": "red"},
                        "then": {"char": "color", "value": "red"},
                    },
                    "priority": 10,
                    "is_active": True,
                    "effective_from": None,
                    "effective_to": None,
                    "referenced_chars": ["color"],
                },
            ],
            "variant_tables": {},
            "dependency_index": {"color": []},  # repaired below once snapshot id is in scope
            "initial_domains": {"color": ["red", "blue"]},
        }
        # Fix dependency_index
        cid = snapshot["constraints"][0]["id"]
        snapshot["dependency_index"] = {"color": [cid]}

        loaded = self.engine._load_from_snapshot(snapshot)
        assert loaded is not None
        char_map, constraints, _vtables, _prebuilt, domains = loaded
        assert "color" in char_map
        assert len(constraints) == 1
        assert isinstance(domains["color"], set)
        assert domains["color"] == {"red", "blue"}

    def test_snapshot_numeric_domains(self):
        snapshot = {
            "schema_version": 1,
            "characteristics": {
                "weight": {
                    "id": str(uuid.uuid4()),
                    "name": "Weight",
                    "slug": "weight",
                    "char_type": "numeric",
                    "is_required": False,
                    "is_multi_select": False,
                    "numeric_min": 0,
                    "numeric_max": 500,
                },
            },
            "constraints": [],
            "variant_tables": {},
            "dependency_index": {},
            "initial_domains": {
                "weight": {"type": "numeric", "min": 0, "max": 500, "step": None},
            },
        }
        loaded = self.engine._load_from_snapshot(snapshot)
        assert loaded is not None
        _, _, _, _, domains = loaded
        assert isinstance(domains["weight"], NumericInterval)
        assert domains["weight"].min == 0
        assert domains["weight"].max == 500

    def test_propagate_with_prebuilt_index(self):
        from app.apps.cpq.models.product import ConstraintType

        rule = MagicMock()
        rule.id = uuid.uuid4()
        rule.name = "test"
        rule.is_active = True
        rule.effective_from = None
        rule.effective_to = None
        rule.constraint_type = ConstraintType.EXCLUDES
        rule.expression = {
            "if": {"char": "engine", "op": "eq", "value": "V8"},
            "then": {"char": "color", "value": "green"},
        }

        prebuilt = {"engine": [rule]}
        domains = {"engine": {"V8", "V6"}, "color": {"red", "blue", "green"}}

        # With prebuilt index
        result = self.engine._propagate(
            domains,
            {"engine": "V8"},
            [rule],
            {},
            {"engine"},
            prebuilt_char_constraints=prebuilt,
        )
        assert "green" not in result.domains["color"]


# ── P1.5: BOM Eager Load Test ───────────────────────────


class TestBOMEagerLoad:
    def test_bom_eager_load_returns_load_option(self):
        from app.apps.cpq.engine.bom_resolver import _bom_eager_load

        load = _bom_eager_load(3)
        assert load is not None

    def test_bom_eager_load_depth_1(self):
        from app.apps.cpq.engine.bom_resolver import _bom_eager_load

        load = _bom_eager_load(1)
        assert load is not None


# ── Validation helper test ──────────────────────────────


class TestQuantityExpressionValidation:
    def test_valid_expression(self):
        from app.apps.cpq.api.boms import _validate_quantity_expression

        # Should not raise
        _validate_quantity_expression(
            {
                "type": "formula",
                "expression": "count * 2 + 1",
                "variables": {"count": "panel_count"},
            }
        )

    def test_none_is_valid(self):
        from app.apps.cpq.api.boms import _validate_quantity_expression

        _validate_quantity_expression(None)

    def test_invalid_type(self):
        from app.apps.cpq.api.boms import _validate_quantity_expression

        with pytest.raises(Exception):
            _validate_quantity_expression({"type": "table"})

    def test_unmapped_variable(self):
        from app.apps.cpq.api.boms import _validate_quantity_expression

        with pytest.raises(Exception):
            _validate_quantity_expression(
                {
                    "type": "formula",
                    "expression": "count * x",
                    "variables": {"count": "panel_count"},
                }
            )

    def test_invalid_syntax(self):
        from app.apps.cpq.api.boms import _validate_quantity_expression

        with pytest.raises(Exception):
            _validate_quantity_expression(
                {
                    "type": "formula",
                    "expression": "count *** 2",
                    "variables": {"count": "x"},
                }
            )
