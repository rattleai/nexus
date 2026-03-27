"""Constraint network analysis — cycle detection, dead values, coverage gaps, satisfiability.

Pure analysis class: loads characteristics and constraints, builds a dependency graph,
and runs various static analyses. No DB writes.
"""

from __future__ import annotations

import time as _time
from collections import defaultdict
from dataclasses import dataclass, field

from app.apps.cpq.engine.engine import (
    CharacteristicInfo,
    ConfiguratorEngine,
    ConstraintRule,
    ConstraintType,
    NumericInterval,
    VariantTable,
)

from app.db.models import Characteristic


@dataclass
class CycleInfo:
    path: list[str]
    involved_rules: list[str]


@dataclass
class DeadValueInfo:
    characteristic: str
    value: str
    reason: str
    excluding_rules: list[str]


@dataclass
class CoverageGapInfo:
    characteristic: str
    is_required: bool
    has_default: bool
    reachable_via_constraints: bool
    gap_description: str


@dataclass
class AnalysisResult:
    cycles: list[CycleInfo] = field(default_factory=list)
    dead_values: list[DeadValueInfo] = field(default_factory=list)
    coverage_gaps: list[CoverageGapInfo] = field(default_factory=list)
    is_satisfiable: bool = True
    satisfiability_note: str = ""
    analysis_duration_ms: float = 0.0


class ConstraintAnalyzer:
    """Analyzes constraint networks for structural issues."""

    def __init__(self):
        self._engine = ConfiguratorEngine()

    def analyze(
        self,
        char_map: dict[str, CharacteristicInfo | Characteristic],
        constraints: list[ConstraintRule],
        variant_tables: dict[str, VariantTable],
    ) -> AnalysisResult:
        start = _time.monotonic()

        # Filter to active constraints only
        active = [c for c in constraints if c.is_active]

        # Build dependency graph
        graph, rule_edges = self._build_dependency_graph(active)

        # Run analyses
        cycles = self._detect_cycles(graph, rule_edges)
        dead_values = self._detect_dead_values(char_map, active)
        coverage_gaps = self._detect_coverage_gaps(char_map, active)
        is_satisfiable, sat_note = self._check_satisfiability(
            char_map, active, variant_tables
        )

        elapsed_ms = (_time.monotonic() - start) * 1000

        return AnalysisResult(
            cycles=cycles,
            dead_values=dead_values,
            coverage_gaps=coverage_gaps,
            is_satisfiable=is_satisfiable,
            satisfiability_note=sat_note,
            analysis_duration_ms=round(elapsed_ms, 2),
        )

    # ── Dependency graph ───────────────────────────────────

    def _build_dependency_graph(
        self, constraints: list[ConstraintRule]
    ) -> tuple[dict[str, set[str]], dict[tuple[str, str], list[str]]]:
        """Build directed dependency graph from constraint expressions.

        Returns:
            graph: {source_char: {target_chars}}
            rule_edges: {(source, target): [rule_ids]}
        """
        graph: dict[str, set[str]] = defaultdict(set)
        rule_edges: dict[tuple[str, str], list[str]] = defaultdict(list)

        for c in constraints:
            expr = c.expression
            ct = c.constraint_type
            rule_id = str(c.id) if hasattr(c, "id") else "unknown"

            sources: set[str] = set()
            targets: set[str] = set()

            if ct in (ConstraintType.REQUIRES, ConstraintType.EXCLUDES):
                sources = self._extract_condition_chars(expr.get("if", {}))
                then_char = expr.get("then", {}).get("char")
                if then_char:
                    targets.add(then_char)

            elif ct == ConstraintType.SELECTION_CONDITION:
                sources = self._extract_condition_chars(expr.get("condition", {}))
                target_char = expr.get("target", {}).get("char")
                if target_char:
                    targets.add(target_char)

            elif ct == ConstraintType.DEFAULT_VALUE:
                sources = self._extract_condition_chars(expr.get("if", {}))
                target_char = expr.get("target")
                if target_char:
                    targets.add(target_char)

            elif ct == ConstraintType.FORMULA:
                variables = expr.get("variables", {})
                sources = set(variables.values())
                target_char = expr.get("target")
                if target_char:
                    targets.add(target_char)

            elif ct == ConstraintType.TABLE:
                table_id = expr.get("table_id")
                # Input/output columns are characteristic slugs
                # We'd need variant table data to know the columns
                # For now, skip TABLE dependencies (conservative)
                pass

            for s in sources:
                for t in targets:
                    graph[s].add(t)
                    rule_edges[(s, t)].append(rule_id)

        return dict(graph), dict(rule_edges)

    def _extract_condition_chars(self, condition: dict) -> set[str]:
        """Extract all characteristic slugs from a condition expression."""
        chars: set[str] = set()
        if not condition:
            return chars
        char_slug = condition.get("char")
        if char_slug:
            chars.add(char_slug)
        # Compound conditions
        for key in ("conditions",):
            if key in condition and isinstance(condition[key], list):
                for sub in condition[key]:
                    chars |= self._extract_condition_chars(sub)
        if "condition" in condition and isinstance(condition["condition"], dict):
            chars |= self._extract_condition_chars(condition["condition"])
        return chars

    # ── Cycle detection (DFS with coloring) ────────────────

    def _detect_cycles(
        self,
        graph: dict[str, set[str]],
        rule_edges: dict[tuple[str, str], list[str]],
    ) -> list[CycleInfo]:
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = defaultdict(int)
        parent: dict[str, str | None] = {}
        cycles: list[CycleInfo] = []

        all_nodes = set(graph.keys())
        for targets in graph.values():
            all_nodes |= targets

        def dfs(node: str, path: list[str]) -> None:
            color[node] = GRAY
            for neighbor in graph.get(node, set()):
                if color[neighbor] == GRAY:
                    # Found a cycle — extract it
                    cycle_start = path.index(neighbor) if neighbor in path else -1
                    if cycle_start >= 0:
                        cycle_path = path[cycle_start:] + [neighbor]
                        involved = []
                        for i in range(len(cycle_path) - 1):
                            edge = (cycle_path[i], cycle_path[i + 1])
                            involved.extend(rule_edges.get(edge, []))
                        cycles.append(CycleInfo(path=cycle_path, involved_rules=involved))
                elif color[neighbor] == WHITE:
                    dfs(neighbor, path + [neighbor])
            color[node] = BLACK

        for node in all_nodes:
            if color[node] == WHITE:
                dfs(node, [node])

        return cycles

    # ── Dead value detection ───────────────────────────────

    def _detect_dead_values(
        self,
        char_map: dict[str, CharacteristicInfo | Characteristic],
        constraints: list[ConstraintRule],
    ) -> list[DeadValueInfo]:
        dead: list[DeadValueInfo] = []

        # Collect all EXCLUDES rules grouped by target characteristic
        excludes_by_target: dict[str, list[ConstraintRule]] = defaultdict(list)
        for c in constraints:
            if c.constraint_type == ConstraintType.EXCLUDES:
                target_char = c.expression.get("then", {}).get("char")
                if target_char:
                    excludes_by_target[target_char].append(c)

        for target_slug, rules in excludes_by_target.items():
            if target_slug not in char_map:
                continue
            char = char_map[target_slug]
            if char.char_type.value != "enum":
                continue

            all_values = {v.value for v in char.values}

            for value in all_values:
                excluding_rules = []
                for rule in rules:
                    excluded_vals = rule.expression.get("then", {}).get("value")
                    if isinstance(excluded_vals, str):
                        excluded_vals = [excluded_vals]
                    if excluded_vals and value in excluded_vals:
                        # Check if the condition is always true (no "if" or empty "if")
                        if_clause = rule.expression.get("if", {})
                        if not if_clause:
                            # Unconditional exclude — value is definitely dead
                            excluding_rules.append(str(rule.id))

                if excluding_rules:
                    dead.append(DeadValueInfo(
                        characteristic=target_slug,
                        value=value,
                        reason=f"Unconditionally excluded by {len(excluding_rules)} rule(s)",
                        excluding_rules=excluding_rules,
                    ))

            # Check if a value is excluded by all possible values of the triggering char
            for value in all_values:
                for rule in rules:
                    excluded_vals = rule.expression.get("then", {}).get("value")
                    if isinstance(excluded_vals, str):
                        excluded_vals = [excluded_vals]
                    if not excluded_vals or value not in excluded_vals:
                        continue
                    if_clause = rule.expression.get("if", {})
                    if not if_clause:
                        continue  # already handled above
                    trigger_slug = if_clause.get("char")
                    trigger_op = if_clause.get("op")
                    trigger_val = if_clause.get("value")
                    if not trigger_slug or trigger_slug not in char_map:
                        continue
                    trigger_char = char_map[trigger_slug]
                    if trigger_char.char_type.value != "enum":
                        continue

                    # Check if there are rules that exclude this value for ALL trigger values
                    trigger_values = {v.value for v in trigger_char.values}
                    covered_values: set[str] = set()
                    for r2 in rules:
                        ev2 = r2.expression.get("then", {}).get("value")
                        if isinstance(ev2, str):
                            ev2 = [ev2]
                        if not ev2 or value not in ev2:
                            continue
                        if2 = r2.expression.get("if", {})
                        if not if2:
                            covered_values = trigger_values  # unconditional covers all
                            break
                        if if2.get("char") == trigger_slug:
                            if if2.get("op") == "eq":
                                covered_values.add(if2.get("value", ""))
                            elif if2.get("op") == "in":
                                in_vals = if2.get("value", [])
                                if isinstance(in_vals, list):
                                    covered_values.update(in_vals)

                    if covered_values >= trigger_values and trigger_values:
                        # Already reported above if unconditional
                        already = any(
                            d.characteristic == target_slug and d.value == value
                            for d in dead
                        )
                        if not already:
                            dead.append(DeadValueInfo(
                                characteristic=target_slug,
                                value=value,
                                reason=f"Excluded for all values of '{trigger_slug}'",
                                excluding_rules=[str(r.id) for r in rules
                                                 if value in (r.expression.get("then", {}).get("value") or [])],
                            ))

        return dead

    # ── Coverage gap detection ─────────────────────────────

    def _detect_coverage_gaps(
        self,
        char_map: dict[str, CharacteristicInfo | Characteristic],
        constraints: list[ConstraintRule],
    ) -> list[CoverageGapInfo]:
        gaps: list[CoverageGapInfo] = []

        # Build set of characteristics that are targets of any rule
        targeted_chars: set[str] = set()
        for c in constraints:
            expr = c.expression
            ct = c.constraint_type
            if ct in (ConstraintType.REQUIRES, ConstraintType.EXCLUDES):
                t = expr.get("then", {}).get("char")
                if t:
                    targeted_chars.add(t)
            elif ct == ConstraintType.SELECTION_CONDITION:
                t = expr.get("target", {}).get("char")
                if t:
                    targeted_chars.add(t)
            elif ct == ConstraintType.DEFAULT_VALUE:
                t = expr.get("target")
                if t:
                    targeted_chars.add(t)
            elif ct == ConstraintType.FORMULA:
                t = expr.get("target")
                if t:
                    targeted_chars.add(t)

        for slug, char in char_map.items():
            is_required = char.is_required
            if not is_required:
                continue

            has_default = bool(char.default_value)
            # Check if any DEFAULT_VALUE constraint targets this char
            if not has_default:
                for c in constraints:
                    if c.constraint_type == ConstraintType.DEFAULT_VALUE:
                        if c.expression.get("target") == slug:
                            has_default = True
                            break

            reachable = slug in targeted_chars

            if not has_default and not reachable:
                gaps.append(CoverageGapInfo(
                    characteristic=slug,
                    is_required=True,
                    has_default=False,
                    reachable_via_constraints=False,
                    gap_description=f"Required characteristic '{slug}' has no default value and is not the target of any constraint rule. Users must always manually select it.",
                ))

        return gaps

    # ── Satisfiability check ───────────────────────────────

    def _check_satisfiability(
        self,
        char_map: dict[str, CharacteristicInfo | Characteristic],
        constraints: list[ConstraintRule],
        variant_tables: dict[str, VariantTable],
    ) -> tuple[bool, str]:
        """Run zero-selection propagation to detect inherent contradictions."""
        domains = self._engine._build_initial_domains(char_map)
        result = self._engine._propagate(
            domains, {}, constraints, variant_tables, set(domains.keys())
        )
        if result.contradictions:
            chars = ", ".join(result.contradictions)
            return False, f"Constraint network is unsatisfiable: empty domains for [{chars}] with no selections"
        return True, "Constraint network is satisfiable (zero-selection propagation found no contradictions)"
