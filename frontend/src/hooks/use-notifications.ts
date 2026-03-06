import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { Notification } from "@/types/api"

export function useNotifications() {
  return useQuery({
    queryKey: queryKeys.notifications.list(),
    queryFn: ({ signal }) =>
      api.get("notifications", { signal }).json<Notification[]>(),
  })
}

export function useUnreadCount() {
  return useQuery({
    queryKey: queryKeys.notifications.unread(),
    queryFn: ({ signal }) =>
      api.get("notifications/unread-count", { signal }).json<{ count: number }>(),
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
