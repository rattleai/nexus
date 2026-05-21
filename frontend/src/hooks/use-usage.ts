import { useMutation, useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { UsageSummary } from "@/types/api"

export function useUsage() {
  return useQuery({
    queryKey: queryKeys.usage.current(),
    queryFn: async ({ signal }): Promise<UsageSummary> => {
      return api.get("billing/usage", { signal }).json<UsageSummary>()
    },
    retry: 1,
    retryDelay: 1000,
  })
}

export function useExportTenantData() {
  return useMutation({
    mutationFn: (body: { format: string }) =>
      api.post("export/tenant", { json: body }).json<{ url: string }>(),
  })
}

export function useExportAccountData() {
  return useMutation({
    mutationFn: (body: { format: string }) =>
      api.post("export/account", { json: body }).json<{ url: string }>(),
  })
}

export function useDeleteAccount() {
  return useMutation({
    mutationFn: () => api.delete("export/account"),
  })
}
