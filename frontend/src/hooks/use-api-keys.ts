import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { ApiKey, ApiKeyCreated, CursorPaginatedResponse } from "@/types/api"

export function useApiKeys() {
  return useQuery({
    queryKey: queryKeys.apiKeys.list(),
    queryFn: ({ signal }) =>
      api.get("api-keys", { signal }).json<CursorPaginatedResponse<ApiKey>>(),
  })
}

export function useCreateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; scopes?: string[] }) =>
      api.post("api-keys", { json: body }).json<ApiKeyCreated>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.apiKeys.all }),
  })
}

export function useRevokeApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`api-keys/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.apiKeys.all }),
  })
}
