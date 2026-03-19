import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import { getBillingReturnUrl } from "@/lib/app-config"
import type { Plan, Subscription } from "@/types/api"

export function useSubscription() {
  return useQuery({
    queryKey: queryKeys.billing.subscription(),
    queryFn: async ({ signal }) => {
      try {
        const data = await api.get("billing/subscription", { signal }).json<Subscription>()
        return data
      } catch (error) {
        console.warn("Failed to fetch subscription:", error)
        throw error
      }
    },
    retry: 1,
    retryDelay: 1000,
  })
}

export function usePlans() {
  return useQuery({
    queryKey: queryKeys.billing.plans(),
    queryFn: async ({ signal }) => {
      try {
        const data = await api.get("billing/plans", { signal }).json<Plan[]>()
        return data || []
      } catch (error) {
        console.warn("Failed to fetch plans:", error)
        throw error
      }
    },
    retry: 1,
    retryDelay: 1000,
  })
}

export function useCreateCheckout() {
  return useMutation({
    mutationFn: (body: { plan_id: string; return_url: string }) =>
      api.post("billing/checkout", { json: body }).json<{ url: string }>(),
  })
}

export function useCancelSubscription() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post("billing/subscription/cancel").json<Subscription>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.billing.all }),
  })
}

export function useBillingPortal() {
  return useMutation({
    mutationFn: async () => {
      // Get the correct return URL based on environment configuration
      const returnUrl = getBillingReturnUrl()
      return api
        .post("billing/portal", {
          json: { return_url: returnUrl },
        })
        .json<{ url: string }>()
    },
  })
}
