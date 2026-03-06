import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { CursorPaginatedResponse, WebhookDelivery, WebhookEndpoint } from "@/types/api"

export function useWebhooks() {
  return useQuery({
    queryKey: queryKeys.webhooks.list(),
    queryFn: ({ signal }) =>
      api.get("webhooks", { signal }).json<WebhookEndpoint[]>(),
  })
}

export function useWebhook(id: string) {
  return useQuery({
    queryKey: queryKeys.webhooks.detail(id),
    queryFn: ({ signal }) =>
      api.get(`webhooks/${id}`, { signal }).json<WebhookEndpoint>(),
    enabled: !!id,
  })
}

export function useCreateWebhook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { url: string; events: string[]; active?: boolean }) =>
      api.post("webhooks", { json: body }).json<WebhookEndpoint>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.webhooks.all }),
  })
}

export function useUpdateWebhook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: string
      url?: string
      events?: string[]
      active?: boolean
    }) => api.patch(`webhooks/${id}`, { json: body }).json<WebhookEndpoint>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.webhooks.all }),
  })
}

export function useDeleteWebhook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`webhooks/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.webhooks.all }),
  })
}

export function useTestWebhook() {
  return useMutation({
    mutationFn: (id: string) => api.post(`webhooks/${id}/test`).json<void>(),
  })
}

export function useWebhookDeliveries(endpointId: string) {
  return useQuery({
    queryKey: queryKeys.webhooks.deliveries(endpointId),
    queryFn: ({ signal }) =>
      api
        .get(`webhooks/${endpointId}/deliveries`, { signal })
        .json<CursorPaginatedResponse<WebhookDelivery>>(),
    enabled: !!endpointId,
  })
}
