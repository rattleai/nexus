import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { AuditLog, CursorPaginatedResponse } from "@/types/api"

interface AuditLogFilters {
  action?: string
  resource_type?: string
  limit?: number
}

export function useAuditLogs(filters?: AuditLogFilters) {
  const searchParams: Record<string, string> = {}
  if (filters?.action) searchParams.action = filters.action
  if (filters?.resource_type) searchParams.resource_type = filters.resource_type
  if (filters?.limit) searchParams.limit = String(filters.limit)

  return useQuery({
    queryKey: queryKeys.auditLogs.list(searchParams),
    queryFn: async ({ signal }) => {
      const res = await api
        .get("audit-logs", {
          searchParams: Object.keys(searchParams).length ? searchParams : undefined,
          signal,
        })
        .json<CursorPaginatedResponse<AuditLog>>()
      return res.items
    },
  })
}
