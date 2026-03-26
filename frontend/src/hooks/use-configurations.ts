import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import { toast } from "sonner"
import type {
  ConfigurationSession,
  ConfiguredBOM,
  ConfigurationPricing,
  BulkActionRequest,
  BulkActionResponse,
  BOMComparisonResult,
  PartFrequencyResponse,
} from "@/types/configurator"
import type { CursorPaginatedResponse } from "@/types/api"

// ── Session Listing (extended) ──────────────────────────

export function useConfigurations(filters?: {
  product_id?: string
  status?: string
  search?: string
  created_after?: string
  created_before?: string
  has_bom?: string
  page_size?: string
}) {
  const params: Record<string, string> = { page_size: filters?.page_size ?? "50" }
  if (filters?.product_id) params.product_id = filters.product_id
  if (filters?.status) params.status = filters.status
  if (filters?.search) params.search = filters.search
  if (filters?.created_after) params.created_after = filters.created_after
  if (filters?.created_before) params.created_before = filters.created_before
  if (filters?.has_bom) params.has_bom = filters.has_bom

  return useQuery({
    queryKey: queryKeys.configurator.sessions.list(params),
    queryFn: async ({ signal }) =>
      api
        .get("configurator/sessions", { searchParams: params, signal })
        .json<CursorPaginatedResponse<ConfigurationSession>>(),
  })
}

// ── Session BOM (cached) ────────────────────────────────

export function useSessionBOM(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.configurator.bom(sessionId ?? ""),
    queryFn: async ({ signal }) => {
      try {
        return await api
          .get(`configurator/sessions/${sessionId}/bom`, { signal })
          .json<ConfiguredBOM>()
      } catch (err: unknown) {
        // 404 means no BOM resolved yet — return null instead of throwing
        if (err && typeof err === "object" && "response" in err) {
          const resp = (err as { response: { status: number } }).response
          if (resp?.status === 404) return null
        }
        throw err
      }
    },
    enabled: !!sessionId,
    retry: false,
  })
}

// ── Session Pricing ─────────────────────────────────────

export function useSessionPricing(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.configurator.pricing(sessionId ?? ""),
    queryFn: async ({ signal }) => {
      try {
        return await api
          .get(`configurator/sessions/${sessionId}/pricing`, { signal })
          .json<ConfigurationPricing>()
      } catch (err: unknown) {
        // 404 means no pricing resolved yet — return null instead of throwing
        if (err && typeof err === "object" && "response" in err) {
          const resp = (err as { response: { status: number } }).response
          if (resp?.status === 404) return null
        }
        throw err
      }
    },
    enabled: !!sessionId,
    retry: false,
  })
}

// ── Clone Session ───────────────────────────────────────

export function useCloneSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) =>
      api
        .post(`configurator/sessions/${sessionId}/clone`)
        .json<ConfigurationSession>(),
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: queryKeys.configurator.sessions.all })
      toast.success(`Configuration cloned: ${session.name || session.id}`)
    },
    onError: () => {
      toast.error("Failed to clone configuration")
    },
  })
}

// ── Delete Session ──────────────────────────────────────

export function useDeleteSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) => {
      await api.delete(`configurator/sessions/${sessionId}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.configurator.sessions.all })
      toast.success("Configuration deleted")
    },
    onError: () => {
      toast.error("Failed to delete configuration")
    },
  })
}

// ── Bulk Action ─────────────────────────────────────────

export function useBulkAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: BulkActionRequest) =>
      api
        .post("configurator/sessions/bulk-action", { json: data })
        .json<BulkActionResponse>(),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: queryKeys.configurator.sessions.all })
      if (result.failed === 0) {
        toast.success(`${result.succeeded} configuration(s) updated`)
      } else {
        toast.warning(`${result.succeeded} succeeded, ${result.failed} failed`)
      }
    },
    onError: () => {
      toast.error("Bulk action failed")
    },
  })
}

// ── BOM Comparison ──────────────────────────────────────

export function useBOMComparison(sessionIds: string[]) {
  return useQuery({
    queryKey: queryKeys.configurator.comparison(sessionIds),
    queryFn: async () =>
      api
        .post("configurator/bom/compare", { json: { session_ids: sessionIds } })
        .json<BOMComparisonResult>(),
    enabled: sessionIds.length >= 2,
  })
}

// ── Part Frequency ──────────────────────────────────────

export function usePartFrequency(filters?: { product_id?: string; limit?: string }) {
  const params: Record<string, string> = {}
  if (filters?.product_id) params.product_id = filters.product_id
  if (filters?.limit) params.limit = filters.limit

  return useQuery({
    queryKey: queryKeys.configurator.partFrequency(params),
    queryFn: async ({ signal }) =>
      api
        .get("configurator/bom/part-frequency", { searchParams: params, signal })
        .json<PartFrequencyResponse>(),
  })
}

// ── Export Session ───────────────────────────────────────

export function useExportSession() {
  return useMutation({
    mutationFn: async ({ sessionId, format }: { sessionId: string; format: "csv" | "json" }) => {
      const response = await api
        .get(`configurator/sessions/${sessionId}/export`, { searchParams: { format } })
        .blob()
      const url = URL.createObjectURL(response)
      const link = document.createElement("a")
      link.href = url
      link.download = `config-${sessionId}.${format}`
      link.click()
      URL.revokeObjectURL(url)
    },
    onSuccess: () => {
      toast.success("Export downloaded")
    },
    onError: () => {
      toast.error("Export failed")
    },
  })
}
