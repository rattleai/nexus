import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { Notification } from "@/types/api"

export function useNotifications() {
  return useQuery({
    queryKey: queryKeys.notifications.list(),
    queryFn: async ({ signal }) => {
      try {
        const data = await api.get("notifications", { signal }).json<Notification[]>()
        return data || []
      } catch (error) {
        console.warn("Failed to fetch notifications:", error)
        return []
      }
    },
    retry: 1,
    retryDelay: 1000,
  })
}

export function useUnreadCount() {
  return useQuery({
    queryKey: queryKeys.notifications.unread(),
    queryFn: async ({ signal }) => {
      try {
        const data = await api.get("notifications/unread-count", { signal }).json<{ count: number }>()
        return data
      } catch (error) {
        console.warn("Failed to fetch unread count:", error)
        return { count: 0 }
      }
    },
    retry: 1,
    retryDelay: 1000,
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
