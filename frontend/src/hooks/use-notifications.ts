import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, getAccessToken } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { Notification } from "@/types/api"

export function useNotifications() {
  return useQuery({
    queryKey: queryKeys.notifications.list(),
    queryFn: async ({ signal }) =>
      api.get("notifications", { signal }).json<Notification[]>(),
    enabled: !!getAccessToken(),
    retry: 1,
    meta: { suppressErrorToast: true },
  })
}

export function useUnreadCount() {
  return useQuery({
    queryKey: queryKeys.notifications.unread(),
    queryFn: async ({ signal }) =>
      api.get("notifications/unread-count", { signal }).json<{ count: number }>(),
    enabled: !!getAccessToken(),
    retry: 1,
    meta: { suppressErrorToast: true },
  })
}

export function useMarkAsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post(`notifications/${id}/read`),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: queryKeys.notifications.all }),
  })
}

export function useMarkAllAsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post("notifications/read-all"),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: queryKeys.notifications.all }),
  })
}
