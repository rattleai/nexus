import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import { toast } from "sonner"
import type {
  ConfigurationSession,
  ConfigurationSessionCreate,
  ConfigurationSelectionRequest,
  SelectionResult,
  ConfigurationTemplate,
  ConfigurationTemplateCreate,
  ConfiguredBOM,
  ConfigurationPricing,
  PricingSimulateRequest,
} from "@/types/configurator"
import type { PaginatedResponse } from "@/types/api"

// ── Session Queries ─────────────────────────────────────

export function useConfiguratorSessions(filters?: {
  product_id?: string
  status?: string
}) {
  const params: Record<string, string> = { page_size: "50" }
  if (filters?.product_id) params.product_id = filters.product_id
  if (filters?.status) params.status = filters.status

  return useQuery({
    queryKey: queryKeys.configurator.sessions.list(params),
    queryFn: async ({ signal }) =>
      api
        .get("configurator/sessions", { searchParams: params, signal })
        .json<PaginatedResponse<ConfigurationSession>>(),
  })
}

export function useConfiguratorSession(id: string | null) {
  return useQuery({
    queryKey: queryKeys.configurator.sessions.detail(id ?? ""),
    queryFn: async ({ signal }) =>
      api.get(`configurator/sessions/${id}`, { signal }).json<ConfigurationSession>(),
    enabled: !!id,
  })
}

export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: ConfigurationSessionCreate) =>
      api.post("configurator/sessions", { json: data }).json<ConfigurationSession>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.configurator.sessions.all })
    },
  })
}

export function useMakeSelection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      sessionId,
      data,
    }: {
      sessionId: string
      data: ConfigurationSelectionRequest
    }) =>
      api
        .post(`configurator/sessions/${sessionId}/select`, { json: data })
        .json<SelectionResult>(),
    onSuccess: (result) => {
      qc.setQueryData(
        queryKeys.configurator.sessions.detail(result.session.id),
        result.session,
      )
    },
  })
}

export function useCompleteSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) =>
      api
        .post(`configurator/sessions/${sessionId}/complete`)
        .json<ConfigurationSession>(),
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: queryKeys.configurator.sessions.all })
      qc.setQueryData(queryKeys.configurator.sessions.detail(session.id), session)
      toast.success("Configuration completed")
    },
  })
}

// ── BOM Resolution ──────────────────────────────────────

export function useResolvedBOM(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.configurator.bom(sessionId ?? ""),
    queryFn: async () =>
      api
        .post(`configurator/sessions/${sessionId}/resolve-bom`)
        .json<ConfiguredBOM>(),
    enabled: false, // manually triggered
  })
}

export function useResolveBOM() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) =>
      api
        .post(`configurator/sessions/${sessionId}/resolve-bom`)
        .json<ConfiguredBOM>(),
    onSuccess: (bom) => {
      qc.setQueryData(queryKeys.configurator.bom(bom.session_id), bom)
    },
  })
}

// ── Pricing ─────────────────────────────────────────────

export function useResolvedPricing(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.configurator.pricing(sessionId ?? ""),
    queryFn: async ({ signal }) =>
      api
        .get(`configurator/pricing/${sessionId}`, { signal })
        .json<ConfigurationPricing>(),
    enabled: !!sessionId,
  })
}

export function useResolvePricing() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) =>
      api
        .post(`configurator/sessions/${sessionId}/resolve-pricing`)
        .json<ConfigurationPricing>(),
    onSuccess: (pricing) => {
      qc.setQueryData(queryKeys.configurator.pricing(pricing.session_id), pricing)
    },
  })
}

export function useSimulatePricing() {
  return useMutation({
    mutationFn: async (data: PricingSimulateRequest) =>
      api
        .post("configurator/pricing/simulate", { json: data })
        .json<ConfigurationPricing>(),
  })
}

// ── Templates ───────────────────────────────────────────

export function useConfigurationTemplates(productId?: string) {
  const params: Record<string, string> = { page_size: "50" }
  if (productId) params.product_id = productId

  return useQuery({
    queryKey: queryKeys.configurator.templates.list(productId),
    queryFn: async ({ signal }) =>
      api
        .get("configurator/templates", { searchParams: params, signal })
        .json<PaginatedResponse<ConfigurationTemplate>>(),
  })
}

export function useConfigurationTemplate(id: string | null) {
  return useQuery({
    queryKey: queryKeys.configurator.templates.detail(id ?? ""),
    queryFn: async ({ signal }) =>
      api.get(`configurator/templates/${id}`, { signal }).json<ConfigurationTemplate>(),
    enabled: !!id,
  })
}

export function useCreateTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: ConfigurationTemplateCreate) =>
      api.post("configurator/templates", { json: data }).json<ConfigurationTemplate>(),
    onSuccess: (template) => {
      qc.invalidateQueries({ queryKey: queryKeys.configurator.templates.all })
      toast.success(`Template "${template.name}" created`)
    },
  })
}

export function useUpdateTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: string
      data: Partial<ConfigurationTemplateCreate>
    }) =>
      api.put(`configurator/templates/${id}`, { json: data }).json<ConfigurationTemplate>(),
    onSuccess: (template) => {
      qc.invalidateQueries({ queryKey: queryKeys.configurator.templates.all })
      toast.success(`Template "${template.name}" updated`)
    },
  })
}

export function useDeleteTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`configurator/templates/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.configurator.templates.all })
      toast.success("Template deleted")
    },
  })
}
