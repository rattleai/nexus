import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { CursorPaginatedResponse, Job } from "@/types/api"

export function useJobs(status?: string) {
  return useQuery({
    queryKey: queryKeys.jobs.list(status),
    queryFn: ({ signal }) =>
      api
        .get("jobs", { searchParams: status ? { status } : undefined, signal })
        .json<CursorPaginatedResponse<Job>>(),
  })
}

export function useJob(id: string) {
  return useQuery({
    queryKey: queryKeys.jobs.detail(id),
    queryFn: ({ signal }) => api.get(`jobs/${id}`, { signal }).json<Job>(),
    enabled: !!id,
  })
}

export function useCreateJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { type: string; payload?: Record<string, unknown>; webhook_url?: string }) =>
      api.post("jobs", { json: body }).json<Job>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.jobs.all }),
  })
}

export function useCancelJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post(`jobs/${id}/cancel`).json<Job>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.jobs.all }),
  })
}
