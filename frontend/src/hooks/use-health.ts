import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import type { HealthResponse } from "@/types/api"

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api.get("health").json<HealthResponse>(),
    refetchInterval: 30_000,
  })
}
