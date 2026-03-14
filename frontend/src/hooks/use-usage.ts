import { useMutation, useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type {
  ApiKey,
  CursorPaginatedResponse,
  Job,
  Subscription,
  TeamMember,
  UsageSummary,
} from "@/types/api"

export function useUsage() {
  return useQuery({
    queryKey: queryKeys.usage.current(),
    queryFn: async ({ signal }): Promise<UsageSummary> => {
      const [jobsResult, apiKeysResult, membersResult, subscriptionResult] =
        await Promise.allSettled([
          api.get("jobs", { signal }).json<CursorPaginatedResponse<Job>>(),
          api.get("api-keys", { signal }).json<CursorPaginatedResponse<ApiKey>>(),
          api.get("team/members", { signal }).json<TeamMember[]>(),
          api.get("billing/subscription", { signal }).json<Subscription>(),
        ])

      // Safely extract limits from subscription, handling both null and failed requests
      let limits: Record<string, number | null> = {}
      if (subscriptionResult.status === "fulfilled" && subscriptionResult.value) {
        try {
          limits = subscriptionResult.value.plan?.limits ?? {}
        } catch (err) {
          console.warn("Failed to extract subscription limits:", err)
        }
      }

      return {
        jobs: {
          used:
            jobsResult.status === "fulfilled" && jobsResult.value
              ? jobsResult.value.items?.length ?? 0
              : 0,
          limit: limits.jobs ?? null,
        },
        api_keys: {
          used:
            apiKeysResult.status === "fulfilled" && apiKeysResult.value
              ? apiKeysResult.value.items?.length ?? 0
              : 0,
          limit: limits.api_keys ?? null,
        },
        team_members: {
          used:
            membersResult.status === "fulfilled" && membersResult.value
              ? membersResult.value.length ?? 0
              : 0,
          limit: limits.team_members ?? null,
        },
        storage_bytes: {
          used: 0,
          limit: limits.storage_bytes ?? null,
        },
      }
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
