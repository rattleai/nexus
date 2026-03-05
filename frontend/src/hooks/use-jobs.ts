import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { CursorPaginatedResponse, Job } from "@/types/api"

export function useJobs(status?: string) {
  const searchParams: Record<string, string> = {}
  if (status) searchParams.status = status

  return useQuery({
    queryKey: queryKeys.jobs.list(status),
    queryFn: () =>
      api.get("jobs", { searchParams }).json<CursorPaginatedResponse<Job>>(),
    refetchInterval: 10_000,
  })
}

export function useJob(jobId: string) {
  return useQuery({
    queryKey: queryKeys.jobs.detail(jobId),
    queryFn: () => api.get(`jobs/${jobId}`).json<Job>(),
    enabled: !!jobId,
    refetchInterval: 5_000,
  })
}

export function useCreateJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { type: string; webhook_url?: string; payload?: Record<string, unknown> }) =>
      api.post("jobs", { json: body }).json<Job>(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all })
    },
  })
}

export function useCancelJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) =>
      api.post(`jobs/${jobId}/cancel`).json<{ id: string; status: string; cancelled: boolean }>(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs.all })
    },
  })
}
