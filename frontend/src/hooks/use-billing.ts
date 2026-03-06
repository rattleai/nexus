import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { Plan, Subscription } from "@/types/api"

export function useSubscription() {
  return useQuery({
    queryKey: queryKeys.billing.subscription(),
    queryFn: ({ signal }) =>
      api.get("billing/subscription", { signal }).json<Subscription>(),
  })
}

export function usePlans() {
  return useQuery({
    queryKey: queryKeys.billing.plans(),
    queryFn: ({ signal }) => api.get("billing/plans", { signal }).json<Plan[]>(),
  })
}

export function useCreateCheckout() {
  return useMutation({
    mutationFn: (body: { price_id: string }) =>
      api.post("billing/checkout", { json: body }).json<{ url: string }>(),
  })
}

export function useCancelSubscription() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post("billing/cancel").json<Subscription>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.billing.all }),
  })
}

export function useBillingPortal() {
  return useMutation({
    mutationFn: () => api.post("billing/portal").json<{ url: string }>(),
  })
}
