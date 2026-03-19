import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query"
import { HTTPError } from "ky"
import { toast } from "sonner"
import { parseApiError } from "./api-client"

function isAuthError(error: unknown): boolean {
  return error instanceof HTTPError && (error.response.status === 401 || error.response.status === 403)
}

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: async (error, query) => {
      // Don't toast for 401/403 — those are handled by auth flow
      if (isAuthError(error)) return
      // Suppress toast for polling queries (e.g., approvals, instances)
      if (query.meta?.suppressErrorToast) return
      const apiError = await parseApiError(error)
      toast.error("Request failed", { description: apiError.detail })
    },
  }),
  mutationCache: new MutationCache({
    onError: async (error) => {
      const apiError = await parseApiError(error)
      toast.error("Action failed", { description: apiError.detail })
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Never retry auth errors — they're handled by the token refresh flow.
      // Retrying 401s amplifies the problem and hammers the refresh endpoint.
      retry: (failureCount, error) => {
        if (isAuthError(error)) return false
        return failureCount < 2
      },
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: false,
    },
  },
})
