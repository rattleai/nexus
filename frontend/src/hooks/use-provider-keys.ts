import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { ProviderKey } from "@/types/api"

export function useProviderKeys() {
  return useQuery({
    queryKey: queryKeys.providerKeys.list(),
    queryFn: ({ signal }) =>
      api.get("ai/provider-keys", { signal }).json<ProviderKey[]>(),
  })
}

export function useCreateProviderKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { provider: string; api_key: string; display_name?: string }) =>
      api.post("ai/provider-keys", { json: body }).json<ProviderKey>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.providerKeys.all }),
  })
}

export function useDeleteProviderKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`ai/provider-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.providerKeys.all }),
  })
}
