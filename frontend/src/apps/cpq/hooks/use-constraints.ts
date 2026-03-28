import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import { toast } from "sonner"
import type {
  ConstraintGroup,
  ConstraintGroupCreate,
  ConstraintGroupUpdate,
  ConstraintRule,
  ConstraintRuleCreate,
  ConstraintRuleUpdate,
  VariantTable,
  VariantTableCreate,
  VariantTableUpdate,
  ConstraintAnalysis,
  ConstraintSimulation,
  ConstraintSimulationRequest,
  ConstraintImpact,
  ConstraintImpactRequest,
} from "@/apps/cpq/types/configurator"
import type { PaginatedResponse } from "@/types/api"

// ── Constraint Group Queries ────────────────────────────

export function useConstraintGroups(productId?: string) {
  const params: Record<string, string> = { page_size: "100" }
  if (productId) params.product_id = productId

  return useQuery({
    queryKey: queryKeys.constraints.groups.list(productId),
    queryFn: async ({ signal }) =>
      api
        .get("constraints/groups", { searchParams: params, signal })
        .json<PaginatedResponse<ConstraintGroup>>(),
  })
}

export function useCreateConstraintGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: ConstraintGroupCreate) =>
      api.post("constraints/groups", { json: data }).json<ConstraintGroup>(),
    onSuccess: (group) => {
      qc.invalidateQueries({ queryKey: queryKeys.constraints.groups.all })
      toast.success(`Constraint group "${group.name}" created`)
    },
  })
}

export function useUpdateConstraintGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: ConstraintGroupUpdate }) =>
      api.put(`constraints/groups/${id}`, { json: data }).json<ConstraintGroup>(),
    onSuccess: (group) => {
      qc.invalidateQueries({ queryKey: queryKeys.constraints.groups.all })
      toast.success(`Constraint group "${group.name}" updated`)
    },
  })
}

export function useDeleteConstraintGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`constraints/groups/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.constraints.groups.all })
      toast.success("Constraint group deleted")
    },
  })
}

// ── Constraint Rule Queries ─────────────────────────────

export function useConstraintRules(filters?: {
  product_id?: string
  constraint_type?: string
  group_id?: string
}) {
  const params: Record<string, string> = { page_size: "200" }
  if (filters?.product_id) params.product_id = filters.product_id
  if (filters?.constraint_type) params.constraint_type = filters.constraint_type
  if (filters?.group_id) params.group_id = filters.group_id

  return useQuery({
    queryKey: queryKeys.constraints.rules.list(params),
    queryFn: async ({ signal }) =>
      api
        .get("constraints/rules", { searchParams: params, signal })
        .json<PaginatedResponse<ConstraintRule>>(),
  })
}

export function useConstraintRule(id: string | null) {
  return useQuery({
    queryKey: queryKeys.constraints.rules.detail(id ?? ""),
    queryFn: async ({ signal }) =>
      api.get(`constraints/rules/${id}`, { signal }).json<ConstraintRule>(),
    enabled: !!id,
  })
}

export function useCreateConstraintRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: ConstraintRuleCreate) =>
      api.post("constraints/rules", { json: data }).json<ConstraintRule>(),
    onSuccess: (rule) => {
      qc.invalidateQueries({ queryKey: queryKeys.constraints.rules.all })
      toast.success(`Rule "${rule.name}" created`)
    },
  })
}

export function useUpdateConstraintRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: ConstraintRuleUpdate }) =>
      api.put(`constraints/rules/${id}`, { json: data }).json<ConstraintRule>(),
    onSuccess: (rule) => {
      qc.invalidateQueries({ queryKey: queryKeys.constraints.rules.all })
      qc.invalidateQueries({ queryKey: queryKeys.constraints.rules.detail(rule.id) })
      toast.success(`Rule "${rule.name}" updated`)
    },
  })
}

export function useDeleteConstraintRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`constraints/rules/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.constraints.rules.all })
      toast.success("Rule deleted")
    },
  })
}

export function useValidateExpression() {
  return useMutation({
    mutationFn: async (data: { expression: Record<string, unknown>; constraint_type: string }) =>
      api
        .post("constraints/rules/validate", { json: data })
        .json<{ is_valid: boolean; errors: string[] }>(),
  })
}

// ── Variant Table Queries ───────────────────────────────

export function useVariantTables(productId?: string) {
  const params: Record<string, string> = { page_size: "100" }
  if (productId) params.product_id = productId

  return useQuery({
    queryKey: queryKeys.constraints.tables.list(productId),
    queryFn: async ({ signal }) =>
      api
        .get("constraints/tables", { searchParams: params, signal })
        .json<PaginatedResponse<VariantTable>>(),
  })
}

export function useCreateVariantTable() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: VariantTableCreate) =>
      api.post("constraints/tables", { json: data }).json<VariantTable>(),
    onSuccess: (table) => {
      qc.invalidateQueries({ queryKey: queryKeys.constraints.tables.all })
      toast.success(`Table "${table.name}" created`)
    },
  })
}

export function useUpdateVariantTable() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: VariantTableUpdate }) =>
      api.put(`constraints/tables/${id}`, { json: data }).json<VariantTable>(),
    onSuccess: (table) => {
      qc.invalidateQueries({ queryKey: queryKeys.constraints.tables.all })
      toast.success(`Table "${table.name}" updated`)
    },
  })
}

export function useDeleteVariantTable() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`constraints/tables/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.constraints.tables.all })
      toast.success("Variant table deleted")
    },
  })
}

// ── Constraint Analysis & Simulation ────────────────────

export function useConstraintAnalysis(productId: string | null) {
  return useQuery({
    queryKey: queryKeys.constraints.analysis(productId ?? ""),
    queryFn: async () =>
      api
        .post("constraints/analysis", { json: { product_id: productId } })
        .json<ConstraintAnalysis>(),
    enabled: false, // manually triggered
  })
}

export function useRunConstraintAnalysis() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (productId: string) =>
      api
        .post("constraints/analysis", { json: { product_id: productId } })
        .json<ConstraintAnalysis>(),
    onSuccess: (_result, productId) => {
      qc.setQueryData(queryKeys.constraints.analysis(productId), _result)
    },
  })
}

export function useSimulateConstraints() {
  return useMutation({
    mutationFn: async (data: ConstraintSimulationRequest) =>
      api.post("constraints/rules/simulate", { json: data }).json<ConstraintSimulation>(),
  })
}

export function useConstraintImpact() {
  return useMutation({
    mutationFn: async (data: ConstraintImpactRequest) =>
      api.post("constraints/impact-analysis", { json: data }).json<ConstraintImpact>(),
  })
}
