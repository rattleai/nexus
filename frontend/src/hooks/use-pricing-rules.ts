import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import { toast } from "sonner"
import type {
  PricingRule,
  PricingRuleCreate,
  PricingRuleUpdate,
} from "@/types/configurator"
import type { PaginatedResponse } from "@/types/api"

// ── Pricing Rule Queries ────────────────────────────────

export function usePricingRules(productId?: string) {
  const params: Record<string, string> = { page_size: "100" }
  if (productId) params.product_id = productId

  return useQuery({
    queryKey: queryKeys.pricingRules.list(productId),
    queryFn: async ({ signal }) =>
      api
        .get("configurator/pricing/rules", { searchParams: params, signal })
        .json<PaginatedResponse<PricingRule>>(),
  })
}

export function useCreatePricingRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: PricingRuleCreate) =>
      api.post("configurator/pricing/rules", { json: data }).json<PricingRule>(),
    onSuccess: (rule) => {
      qc.invalidateQueries({ queryKey: queryKeys.pricingRules.all })
      toast.success(`Pricing rule "${rule.name}" created`)
    },
  })
}

export function useUpdatePricingRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: PricingRuleUpdate }) =>
      api.put(`configurator/pricing/rules/${id}`, { json: data }).json<PricingRule>(),
    onSuccess: (rule) => {
      qc.invalidateQueries({ queryKey: queryKeys.pricingRules.all })
      toast.success(`Pricing rule "${rule.name}" updated`)
    },
  })
}

export function useDeletePricingRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`configurator/pricing/rules/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.pricingRules.all })
      toast.success("Pricing rule deleted")
    },
  })
}
