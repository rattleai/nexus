import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { parseApiError } from "./api-client"

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: async (error) => {
      const apiError = await parseApiError(error)
      // Don't toast for 401/403 — those are handled by auth flow
      if (apiError.code !== "HTTP_401" && apiError.code !== "HTTP_403") {
        toast.error("Request failed", { description: apiError.detail })
      }
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
      retry: 2,
      refetchOnWindowFocus: true,
    },
    mutations: {
      retry: false,
    },
  },
})
