// ── AST types matching backend engine.py:1021-1096 ─────────────

export type LeafOperator =
  | "eq"
  | "neq"
  | "in"
  | "not_in"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "between"

export type CompoundOperator = "and" | "or"

export interface LeafCondition {
  char: string // characteristic slug
  op: LeafOperator
  value: string | string[] | number | [number, number]
}

export interface CompoundCondition {
  op: CompoundOperator
  conditions: ConditionNode[]
}

export interface NotCondition {
  op: "not"
  condition: ConditionNode
}

export type ConditionNode = LeafCondition | CompoundCondition | NotCondition

// ── Type guards ────────────────────────────────────────────────

export function isLeafCondition(node: ConditionNode): node is LeafCondition {
  return "char" in node && "value" in node
}

export function isCompoundCondition(
  node: ConditionNode,
): node is CompoundCondition {
  return (
    "conditions" in node && (node.op === "and" || node.op === "or")
  )
}

export function isNotCondition(node: ConditionNode): node is NotCondition {
  return node.op === "not" && "condition" in node
}
