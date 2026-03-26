import type { CharType, Characteristic } from "@/types/configurator"
import type {
  LeafCondition,
  LeafOperator,
  CompoundCondition,
  ConditionNode,
} from "./condition-types"
import {
  isLeafCondition,
  isCompoundCondition,
  isNotCondition,
} from "./condition-types"

// ── Factory helpers ────────────────────────────────────────────

export function createEmptyLeaf(charSlug?: string): LeafCondition {
  return {
    char: charSlug ?? "",
    op: "eq",
    value: "",
  }
}

export function createEmptyGroup(
  op: "and" | "or" = "and",
): CompoundCondition {
  return {
    op,
    conditions: [],
  }
}

// ── Operator metadata ──────────────────────────────────────────

const OPERATOR_LABELS: Record<LeafOperator, string> = {
  eq: "equals",
  neq: "not equals",
  in: "in",
  not_in: "not in",
  gt: ">",
  gte: ">=",
  lt: "<",
  lte: "<=",
  between: "between",
}

const OPERATORS_BY_TYPE: Record<CharType, LeafOperator[]> = {
  enum: ["eq", "neq", "in", "not_in"],
  numeric: ["eq", "neq", "gt", "gte", "lt", "lte", "between"],
  boolean: ["eq"],
  text: ["eq", "neq"],
}

export function getOperatorsForType(charType: CharType): LeafOperator[] {
  return OPERATORS_BY_TYPE[charType] ?? ["eq"]
}

export function getOperatorLabel(op: LeafOperator): string {
  return OPERATOR_LABELS[op] ?? op
}

// ── Human-readable summary ─────────────────────────────────────

function resolveCharName(
  slug: string,
  characteristics: Characteristic[],
): string {
  const char = characteristics.find((c) => c.slug === slug)
  return char?.name ?? slug
}

function resolveValueLabel(
  slug: string,
  value: string,
  characteristics: Characteristic[],
): string {
  const char = characteristics.find((c) => c.slug === slug)
  if (!char) return value
  const cv = char.values.find((v) => v.value === value)
  return cv?.label ?? value
}

function formatValue(
  node: LeafCondition,
  characteristics: Characteristic[],
): string {
  const { char, op, value } = node

  if (op === "between" && Array.isArray(value) && value.length === 2) {
    return `${value[0]} to ${value[1]}`
  }

  if ((op === "in" || op === "not_in") && Array.isArray(value)) {
    const labels = value.map((v) =>
      resolveValueLabel(char, String(v), characteristics),
    )
    return `[${labels.join(", ")}]`
  }

  if (typeof value === "string") {
    return resolveValueLabel(char, value, characteristics)
  }

  return String(value)
}

function leafToSummary(
  node: LeafCondition,
  characteristics: Characteristic[],
): string {
  const name = resolveCharName(node.char, characteristics)
  const opLabel = getOperatorLabel(node.op)
  const val = formatValue(node, characteristics)
  return `${name} ${opLabel} ${val}`
}

export function conditionToSummary(
  node: ConditionNode | null,
  characteristics: Characteristic[],
): string {
  if (!node) return "Always"

  if (isLeafCondition(node)) {
    return leafToSummary(node, characteristics)
  }

  if (isNotCondition(node)) {
    return `NOT (${conditionToSummary(node.condition, characteristics)})`
  }

  if (isCompoundCondition(node)) {
    const { op, conditions } = node
    const connector = op.toUpperCase()

    if (conditions.length === 0) return "Always"

    if (conditions.length <= 3) {
      return conditions
        .map((c) => conditionToSummary(c, characteristics))
        .join(` ${connector} `)
    }

    return `${conditions.length} conditions (${connector})`
  }

  return "Unknown"
}

// ── Client-side evaluation (mirrors engine.py:1021-1096) ───────

export function evaluateCondition(
  node: ConditionNode | null,
  selections: Record<string, string | string[]>,
): boolean {
  if (!node) return true

  if (isCompoundCondition(node)) {
    if (node.op === "and") {
      return node.conditions.every((c) => evaluateCondition(c, selections))
    }
    return node.conditions.some((c) => evaluateCondition(c, selections))
  }

  if (isNotCondition(node)) {
    return !evaluateCondition(node.condition, selections)
  }

  if (!isLeafCondition(node)) return true

  const { char, op, value: expected } = node
  if (!char) return true

  const currentValue = selections[char]
  if (currentValue === undefined || currentValue === null) return false

  const isMulti = Array.isArray(currentValue)

  if (op === "eq") {
    if (isMulti) return currentValue.includes(String(expected))
    return currentValue === String(expected)
  }

  if (op === "neq") {
    if (isMulti) return !currentValue.includes(String(expected))
    return currentValue !== String(expected)
  }

  if (op === "in") {
    if (!Array.isArray(expected)) return false
    const expectedStrs = expected.map(String)
    if (isMulti) {
      const currentSet = new Set(currentValue)
      return expectedStrs.some((v) => currentSet.has(v))
    }
    return expectedStrs.includes(currentValue)
  }

  if (op === "not_in") {
    if (!Array.isArray(expected)) return true
    const expectedStrs = expected.map(String)
    if (isMulti) {
      const currentSet = new Set(currentValue)
      return !expectedStrs.some((v) => currentSet.has(v))
    }
    return !expectedStrs.includes(currentValue)
  }

  // Numeric operators don't apply to multi-select
  if (isMulti) return false

  if (op === "gt" || op === "gte" || op === "lt" || op === "lte") {
    const cv = parseFloat(currentValue)
    const ev =
      typeof expected === "number"
        ? expected
        : parseFloat(String(expected))
    if (isNaN(cv) || isNaN(ev)) return false

    if (op === "gt") return cv > ev
    if (op === "gte") return cv >= ev
    if (op === "lt") return cv < ev
    if (op === "lte") return cv <= ev
  }

  if (op === "between") {
    if (Array.isArray(expected) && expected.length === 2) {
      const cv = parseFloat(currentValue)
      const lo = parseFloat(String(expected[0]))
      const hi = parseFloat(String(expected[1]))
      if (isNaN(cv) || isNaN(lo) || isNaN(hi)) return false
      return lo <= cv && cv <= hi
    }
    return false
  }

  return true
}
