import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { toast } from "sonner"
import type {
  AgentDefinition,
  AgentDefinitionCreate,
  AgentDefinitionUpdate,
  AgentInstance,
  AgentPolicy,
  AgentAnalytics,
  TenantTool,
  PaginatedAgentResponse,
} from "@/types/agents"

// ── Query Keys ────────────────────────────────────────────────────

export const agentKeys = {
  all: ["agents"] as const,
  definitions: {
    all: ["agents", "definitions"] as const,
    list: (status?: string) => ["agents", "definitions", "list", status] as const,
    detail: (id: string) => ["agents", "definitions", "detail", id] as const,
  },
  instances: {
    all: ["agents", "instances"] as const,
    list: (agentId: string, status?: string) =>
      ["agents", "instances", "list", agentId, status] as const,
    detail: (id: string) => ["agents", "instances", "detail", id] as const,
  },
  tools: {
    all: ["agents", "tools"] as const,
    list: () => ["agents", "tools", "list"] as const,
  },
  policies: {
    all: ["agents", "policies"] as const,
    list: () => ["agents", "policies", "list"] as const,
  },
  analytics: (days?: number, agentId?: string) =>
    ["agents", "analytics", days, agentId] as const,
  approvals: () => ["agents", "approvals"] as const,
} as const

// ── Agent Definition Queries ──────────────────────────────────────

export function useAgentDefinitions(status?: string) {
  return useQuery({
    queryKey: agentKeys.definitions.list(status),
    queryFn: async ({ signal }) => {
      const params: Record<string, string> = { page_size: "100" }
      if (status && status !== "all") params.status = status
      return api
        .get("agents/definitions", { searchParams: params, signal })
        .json<PaginatedAgentResponse<AgentDefinition>>()
    },
  })
}

export function useAgentDefinition(id: string | null) {
  return useQuery({
    queryKey: agentKeys.definitions.detail(id ?? ""),
    queryFn: async () =>
      api.get(`agents/definitions/${id}`).json<AgentDefinition>(),
    enabled: !!id,
  })
}

export function useCreateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (data: AgentDefinitionCreate) =>
      api.post("agents/definitions", { json: data }).json<AgentDefinition>(),
    onSuccess: (agent) => {
      qc.invalidateQueries({ queryKey: agentKeys.definitions.all })
      toast.success(`Agent "${agent.name}" created`)
    },
    // No onError — global MutationCache.onError shows the API error detail
  })
}

export function useUpdateAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: AgentDefinitionUpdate }) =>
      api.put(`agents/definitions/${id}`, { json: data }).json<AgentDefinition>(),
    onSuccess: (agent) => {
      qc.invalidateQueries({ queryKey: agentKeys.definitions.all })
      qc.invalidateQueries({ queryKey: agentKeys.definitions.detail(agent.id) })
      toast.success(`Agent "${agent.name}" updated`)
    },
  })
}

export function useDeleteAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`agents/definitions/${id}`)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentKeys.definitions.all })
      toast.success("Agent deleted")
    },
  })
}

// ── Instance Queries ──────────────────────────────────────────────

export function useAgentInstances(agentId: string | null, status?: string) {
  return useQuery({
    queryKey: agentKeys.instances.list(agentId ?? "", status),
    queryFn: async () => {
      const params: Record<string, string> = { page_size: "50" }
      if (status) params.status = status
      return api
        .get(`agents/definitions/${agentId}/instances`, { searchParams: params })
        .json<PaginatedAgentResponse<AgentInstance>>()
    },
    enabled: !!agentId,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    meta: { suppressErrorToast: true },
  })
}

export function useRunAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ agentId, input }: { agentId: string; input: Record<string, unknown> }) =>
      api
        .post(`agents/definitions/${agentId}/instances`, {
          json: { input_data: input, idempotency_key: crypto.randomUUID() },
        })
        .json<AgentInstance>(),
    onSuccess: (instance) => {
      qc.invalidateQueries({ queryKey: agentKeys.instances.all })
      toast.success("Agent run started")
    },
  })
}

export function useStopInstance() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (instanceId: string) =>
      api.post(`agents/instances/${instanceId}/stop`).json<AgentInstance>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentKeys.instances.all })
      toast.success("Agent stopped")
    },
  })
}

// ── Tools Queries ─────────────────────────────────────────────────

export function useAgentTools() {
  return useQuery({
    queryKey: agentKeys.tools.list(),
    queryFn: async ({ signal }) =>
      api
        .get("agents/tools", { searchParams: { page_size: "100" }, signal })
        .json<PaginatedAgentResponse<TenantTool>>(),
  })
}

// ── Policy Queries ────────────────────────────────────────────────

export function useAgentPolicies() {
  return useQuery({
    queryKey: agentKeys.policies.list(),
    queryFn: async ({ signal }) =>
      api
        .get("agents/policies", { searchParams: { page_size: "100" }, signal })
        .json<PaginatedAgentResponse<AgentPolicy>>(),
  })
}

// ── Analytics ─────────────────────────────────────────────────────

export function useAgentAnalytics(days = 30, agentId?: string) {
  return useQuery({
    queryKey: agentKeys.analytics(days, agentId),
    queryFn: async ({ signal }) => {
      const params: Record<string, string> = { days: String(days) }
      if (agentId) params.agent_id = agentId
      return api
        .get("agents/analytics", { searchParams: params, signal })
        .json<AgentAnalytics>()
    },
  })
}

// ── Approvals ─────────────────────────────────────────────────────

export function usePendingApprovals() {
  return useQuery({
    queryKey: agentKeys.approvals(),
    queryFn: async () =>
      api
        .get("agents/approvals")
        .json<{ approvals: Array<Record<string, unknown>>; count: number }>(),
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
    // Suppress global error toast for polling — only show errors when user actively queries
    meta: { suppressErrorToast: true },
  })
}
