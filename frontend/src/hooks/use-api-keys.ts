import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { CursorPaginatedResponse, ApiKey, ApiKeyCreated } from "@/types/api"

export function useApiKeys() {
  return useQuery({
    queryKey: queryKeys.apiKeys.list(),
    queryFn: () => api.get("api-keys").json<CursorPaginatedResponse<ApiKey>>(),
  })
}

export function useCreateApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; scopes?: string[] }) =>
      api.post("api-keys", { json: body }).json<ApiKeyCreated>(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys.all })
    },
  })
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (keyId: string) =>
      api.delete(`api-keys/${keyId}`).json<{ id: string; revoked: boolean }>(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys.all })
    },
  })
}
