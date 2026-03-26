// ── Product Family ───────────────────────────────────────

export interface ProductFamily {
  id: string
  name: string
  slug: string
  description: string | null
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ProductFamilyCreate {
  name: string
  slug: string
  description?: string | null
  metadata?: Record<string, unknown> | null
}

export interface ProductFamilyUpdate {
  name?: string
  description?: string | null
  metadata?: Record<string, unknown> | null
}

// ── Product ─────────────────────────────────────────────

export type ProductStatus = "draft" | "active" | "deprecated" | "archived"

export interface Product {
  id: string
  name: string
  slug: string
  family_id: string | null
  description: string | null
  sku_prefix: string | null
  status: ProductStatus
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface ProductCreate {
  name: string
  slug: string
  family_id?: string | null
  description?: string | null
  sku_prefix?: string | null
  status?: ProductStatus
  metadata?: Record<string, unknown> | null
}

export interface ProductUpdate {
  name?: string
  family_id?: string | null
  description?: string | null
  sku_prefix?: string | null
  status?: ProductStatus
  metadata?: Record<string, unknown> | null
}

export interface ProductVersion {
  id: string
  product_id: string
  version_number: number
  label: string | null
  is_active: boolean
  published_at: string | null
  created_at: string
}

export interface ProductVersionCreate {
  label?: string | null
}

// ── Characteristic ──────────────────────────────────────

export type CharType = "enum" | "numeric" | "boolean" | "text"

export interface CharacteristicGroup {
  id: string
  name: string
  slug: string
  description: string | null
  display_order: number
  created_at: string
}

export interface CharacteristicGroupCreate {
  name: string
  slug: string
  description?: string | null
  display_order?: number
}

export interface CharacteristicGroupUpdate {
  name?: string
  description?: string | null
  display_order?: number
}

export interface CharacteristicValue {
  id: string
  characteristic_id: string
  value: string
  label: string
  description: string | null
  display_order: number
  is_default: boolean
  price_adjustment: number | null
  image_url: string | null
}

export interface CharacteristicValueCreate {
  value: string
  label: string
  description?: string | null
  display_order?: number
  is_default?: boolean
  price_adjustment?: number | null
  image_url?: string | null
}

export interface CharacteristicValueUpdate {
  label?: string
  description?: string | null
  display_order?: number
  is_default?: boolean
  price_adjustment?: number | null
  image_url?: string | null
}

export interface Characteristic {
  id: string
  name: string
  slug: string
  group_id: string | null
  description: string | null
  char_type: CharType
  numeric_min: number | null
  numeric_max: number | null
  numeric_step: number | null
  unit: string | null
  is_required: boolean
  is_multi_select: boolean
  default_value: string | null
  display_order: number
  values: CharacteristicValue[]
  created_at: string
}

export interface CharacteristicCreate {
  name: string
  slug: string
  group_id?: string | null
  description?: string | null
  char_type: CharType
  numeric_min?: number | null
  numeric_max?: number | null
  numeric_step?: number | null
  unit?: string | null
  is_required?: boolean
  is_multi_select?: boolean
  default_value?: string | null
  display_order?: number
}

export interface CharacteristicUpdate {
  name?: string
  group_id?: string | null
  description?: string | null
  numeric_min?: number | null
  numeric_max?: number | null
  numeric_step?: number | null
  unit?: string | null
  is_required?: boolean
  is_multi_select?: boolean
  default_value?: string | null
  display_order?: number
}

export interface CharacteristicAssignment {
  id: string
  product_id: string
  characteristic_id: string
  display_order: number
  is_required: boolean | null
  default_value: string | null
  min_select: number | null
  max_select: number | null
}

export interface CharacteristicAssignmentCreate {
  product_id: string
  characteristic_id: string
  display_order?: number
  is_required?: boolean | null
  default_value?: string | null
  min_select?: number | null
  max_select?: number | null
}

// ── Constraint ──────────────────────────────────────────

export type ConstraintType =
  | "requires"
  | "excludes"
  | "selection_condition"
  | "default_value"
  | "formula"
  | "table"

export interface ConstraintGroup {
  id: string
  product_id: string
  name: string
  description: string | null
  is_active: boolean
  created_at: string
}

export interface ConstraintGroupCreate {
  product_id: string
  name: string
  description?: string | null
  is_active?: boolean
}

export interface ConstraintGroupUpdate {
  name?: string
  description?: string | null
  is_active?: boolean
}

export interface ConstraintRule {
  id: string
  product_id: string
  group_id: string | null
  name: string
  description: string | null
  constraint_type: ConstraintType
  expression: Record<string, unknown>
  priority: number
  is_active: boolean
  effective_from: string | null
  effective_to: string | null
  created_at: string
}

export interface ConstraintRuleCreate {
  product_id: string
  group_id?: string | null
  name: string
  description?: string | null
  constraint_type: ConstraintType
  expression: Record<string, unknown>
  priority?: number
  is_active?: boolean
  effective_from?: string | null
  effective_to?: string | null
}

export interface ConstraintRuleUpdate {
  group_id?: string | null
  name?: string
  description?: string | null
  expression?: Record<string, unknown>
  priority?: number
  is_active?: boolean
  effective_from?: string | null
  effective_to?: string | null
}

export interface VariantTable {
  id: string
  product_id: string
  name: string
  description: string | null
  columns: Record<string, unknown>[]
  rows: Record<string, unknown>[]
  input_columns: string[]
  output_columns: string[]
  created_at: string
}

export interface VariantTableCreate {
  product_id: string
  name: string
  description?: string | null
  columns: Record<string, unknown>[]
  rows: Record<string, unknown>[]
  input_columns: string[]
  output_columns: string[]
}

export interface VariantTableUpdate {
  name?: string
  description?: string | null
  columns?: Record<string, unknown>[]
  rows?: Record<string, unknown>[]
  input_columns?: string[]
  output_columns?: string[]
}

// ── BOM ─────────────────────────────────────────────────

export type BOMItemType = "component" | "sub_assembly" | "phantom" | "reference"

export interface BOMHeader {
  id: string
  product_id: string
  name: string
  description: string | null
  bom_type: string
  is_primary: boolean
  effective_from: string | null
  effective_to: string | null
  created_at: string
}

export interface BOMHeaderCreate {
  product_id: string
  name: string
  description?: string | null
  bom_type?: string
  is_primary?: boolean
  effective_from?: string | null
  effective_to?: string | null
}

export interface BOMHeaderUpdate {
  name?: string
  description?: string | null
  bom_type?: string
  is_primary?: boolean
  effective_from?: string | null
  effective_to?: string | null
}

export interface BOMItem {
  id: string
  bom_header_id: string
  parent_item_id: string | null
  item_type: BOMItemType
  part_number: string
  part_name: string
  description: string | null
  quantity: number
  quantity_expression: Record<string, unknown> | null
  unit_of_measure: string
  sub_product_id: string | null
  selection_condition: Record<string, unknown> | null
  sort_order: number
  is_optional: boolean
  unit_cost: number | null
  lead_time_days: number | null
  children: BOMItem[]
}

export interface BOMItemCreate {
  parent_item_id?: string | null
  item_type?: BOMItemType
  part_number: string
  part_name: string
  description?: string | null
  quantity?: number
  quantity_expression?: Record<string, unknown> | null
  unit_of_measure?: string
  sub_product_id?: string | null
  selection_condition?: Record<string, unknown> | null
  effective_from?: string | null
  effective_to?: string | null
  sort_order?: number
  is_optional?: boolean
  unit_cost?: number | null
  lead_time_days?: number | null
}

export interface BOMItemUpdate {
  parent_item_id?: string | null
  item_type?: BOMItemType
  part_number?: string
  part_name?: string
  description?: string | null
  quantity?: number
  quantity_expression?: Record<string, unknown> | null
  unit_of_measure?: string
  sub_product_id?: string | null
  selection_condition?: Record<string, unknown> | null
  effective_from?: string | null
  effective_to?: string | null
  sort_order?: number
  is_optional?: boolean
  unit_cost?: number | null
  lead_time_days?: number | null
}

export interface BOMHeaderDetail extends BOMHeader {
  items: BOMItem[]
}

export interface WhereUsedResult {
  bom_header_id: string
  bom_name: string
  product_id: string
  product_name: string
  item_id: string
  part_number: string
  quantity: number
}

// ── Configuration Session ───────────────────────────────

export type SessionStatus = "in_progress" | "complete" | "invalid" | "locked"

export interface ConfigurationSelection {
  id: string
  characteristic_id: string
  value: string
  is_auto_set: boolean
  set_by_rule_id: string | null
}

export interface ConfigurationSelectionRequest {
  characteristic_id: string
  value: string
}

export interface ConfigurationSession {
  id: string
  product_id: string
  product_version_id: string | null
  user_id: string | null
  name: string | null
  status: SessionStatus
  is_valid: boolean
  is_complete: boolean
  validation_errors: Record<string, unknown>[] | null
  available_domains: Record<string, unknown> | null
  template_id: string | null
  external_reference: string | null
  selections: ConfigurationSelection[]
  created_at: string
  updated_at: string
}

export interface ConfigurationSessionCreate {
  product_id: string
  product_version_id?: string | null
  name?: string | null
  template_id?: string | null
  external_reference?: string | null
}

export interface ConflictStep {
  rule_id: string | null
  rule_name: string | null
  constraint_type: string
  target_char: string
  removed_values: string[]
  triggered_by: Record<string, string>
}

export interface ConflictExplanation {
  characteristic: string
  trace: ConflictStep[]
  contributing_selections: Record<string, string>
}

export interface SelectionResult {
  session: ConfigurationSession
  auto_set_values: Record<string, string>
  excluded_values: Record<string, string[]>
  conflict_explanations: ConflictExplanation[]
}

// ── Configuration Template ──────────────────────────────

export interface ConfigurationTemplate {
  id: string
  product_id: string
  name: string
  description: string | null
  is_partial: boolean
  is_public: boolean
  selections: Record<string, string>[]
  created_at: string
}

export interface ConfigurationTemplateCreate {
  product_id: string
  name: string
  description?: string | null
  is_partial?: boolean
  is_public?: boolean
  selections?: Record<string, string>[]
}

// ── Configured BOM ──────────────────────────────────────

export interface ConfiguredBOM {
  id: string
  session_id: string
  bom_header_id: string
  resolved_items: Record<string, unknown>[]
  total_components: number
  total_cost: number | null
  selection_snapshot: Record<string, string>
  resolved_at: string
  resolution_duration_ms: number | null
}

// ── Pricing ─────────────────────────────────────────────

export type PricingRuleType =
  | "base_price"
  | "option_surcharge"
  | "volume_discount"
  | "conditional"
  | "formula"
  | "tiered"
  | "margin"

export interface PricingRule {
  id: string
  product_id: string
  name: string
  description: string | null
  rule_type: PricingRuleType
  expression: Record<string, unknown>
  priority: number
  is_active: boolean
  effective_from: string | null
  effective_to: string | null
  currency: string
  created_at: string
}

export interface PricingRuleCreate {
  product_id: string
  name: string
  description?: string | null
  rule_type: PricingRuleType
  expression: Record<string, unknown>
  priority?: number
  is_active?: boolean
  effective_from?: string | null
  effective_to?: string | null
  currency?: string
}

export interface PricingRuleUpdate {
  name?: string
  description?: string | null
  expression?: Record<string, unknown>
  priority?: number
  is_active?: boolean
  effective_from?: string | null
  effective_to?: string | null
  currency?: string
}

export interface ConfigurationPricing {
  id: string
  session_id: string
  currency: string
  base_price: number
  total_adjustments: number
  final_price: number
  total_cost: number
  margin_amount: number
  margin_percentage: number
  price_breakdown: Record<string, unknown>[]
  is_profitable: boolean
  resolved_at: string
}

export interface PricingSimulateRequest {
  product_id: string
  selections: Record<string, string>
}

// ── Constraint Analysis ─────────────────────────────────

export interface CycleInfo {
  path: string[]
  involved_rules: string[]
}

export interface DeadValue {
  characteristic: string
  value: string
  reason: string
  excluding_rules: string[]
}

export interface CoverageGap {
  characteristic: string
  is_required: boolean
  has_default: boolean
  reachable_via_constraints: boolean
  gap_description: string
}

export interface ConstraintAnalysis {
  cycles: CycleInfo[]
  dead_values: DeadValue[]
  coverage_gaps: CoverageGap[]
  is_satisfiable: boolean
  satisfiability_note: string
  analysis_duration_ms: number
}

export interface ConstraintSimulationRequest {
  product_id: string
  selections?: Record<string, string>
}

export interface ConstraintSimulation {
  available_domains: Record<string, unknown>
  auto_set_values: Record<string, string>
  excluded_values: Record<string, string[]>
  contradictions: string[]
  conflict_explanations: Record<string, unknown>[]
  is_valid: boolean
  is_complete: boolean
}

export interface ConstraintImpactRequest {
  product_id: string
  rule_id?: string | null
  rule_expression?: Record<string, unknown> | null
  rule_constraint_type?: string | null
  selections?: Record<string, string>
}

export interface CharacteristicImpact {
  characteristic: string
  values_pruned: string[]
  domain_before: unknown
  domain_after: unknown
  was_auto_set: boolean
}

export interface ConstraintImpact {
  affected_characteristics: CharacteristicImpact[]
  new_contradictions: string[]
  new_auto_sets: Record<string, string>
  total_values_pruned: number
}
