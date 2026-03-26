import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { toast } from "sonner"
import type {
  AgentDefinition,
  AgentDefinitionCreate,
  AgentDefinitionUpdate,
  AgentDefinitionMemoryEntry,
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
    allActive: () => ["agents", "instances", "all-active"] as const,
    detail: (id: string) => ["agents", "instances", "detail", id] as const,
  },
  memory: {
    definition: (agentId: string, namespace?: string) =>
      ["agents", "memory", "definition", agentId, namespace] as const,
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

export function useInstanceDetail(instanceId: string | null) {
  return useQuery({
    queryKey: agentKeys.instances.detail(instanceId ?? ""),
    queryFn: async ({ signal }) =>
      api.get(`agents/instances/${instanceId}`, { signal }).json<AgentInstance>(),
    enabled: !!instanceId,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
    meta: { suppressErrorToast: true },
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

// ── Cross-Definition Instance Queries ────────────────────────────

export function useAllActiveInstances(opts?: { enabled?: boolean }) {
  return useQuery({
    queryKey: agentKeys.instances.allActive(),
    queryFn: async ({ signal }) =>
      api
        .get("agents/instances", {
          searchParams: { status: "running,pending", page_size: "50" },
          signal,
        })
        .json<PaginatedAgentResponse<AgentInstance>>(),
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
    enabled: opts?.enabled ?? true,
    meta: { suppressErrorToast: true },
  })
}

export function useAllInstances(status?: string, page = 1, pageSize = 25) {
  return useQuery({
    queryKey: [...agentKeys.instances.all, "global", status, page, pageSize],
    queryFn: async ({ signal }) => {
      const params: Record<string, string> = {
        page_size: String(pageSize),
        page: String(page),
      }
      if (status && status !== "all") params.status = status
      return api
        .get("agents/instances", { searchParams: params, signal })
        .json<PaginatedAgentResponse<AgentInstance>>()
    },
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
    meta: { suppressErrorToast: true },
  })
}

// ── Approvals ─────────────────────────────────────────────────────

export function useResolveApproval() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      approvalId,
      decision,
    }: {
      approvalId: string
      decision: "approved" | "denied"
    }) =>
      api
        .post(`agents/approvals/${approvalId}/resolve`, {
          json: { decision },
        })
        .json<Record<string, unknown>>(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentKeys.approvals() })
      qc.invalidateQueries({ queryKey: agentKeys.instances.all })
      toast.success("Approval resolved")
    },
  })
}

// ── Definition-Scoped Memory ─────────────────────────────────────

export function useDefinitionMemory(agentId: string | null, namespace?: string) {
  return useQuery({
    queryKey: agentKeys.memory.definition(agentId ?? "", namespace),
    queryFn: async ({ signal }) => {
      const params: Record<string, string> = {}
      if (namespace) params.namespace = namespace
      return api
        .get(`agents/definitions/${agentId}/memory`, { searchParams: params, signal })
        .json<AgentDefinitionMemoryEntry[]>()
    },
    enabled: !!agentId,
    refetchInterval: 10_000,
    meta: { suppressErrorToast: true },
  })
}

export function useWriteDefinitionMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      agentId,
      key,
      value,
      namespace,
    }: {
      agentId: string
      key: string
      value: Record<string, unknown>
      namespace?: string
    }) =>
      api
        .put(`agents/definitions/${agentId}/memory`, {
          json: { key, value, namespace },
        })
        .json<AgentDefinitionMemoryEntry>(),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({
        queryKey: agentKeys.memory.definition(vars.agentId),
      })
    },
  })
}

export function useDeleteDefinitionMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      agentId,
      key,
      namespace,
    }: {
      agentId: string
      key?: string
      namespace?: string
    }) => {
      const params: Record<string, string> = {}
      if (key) params.key = key
      if (namespace) params.namespace = namespace
      await api.delete(`agents/definitions/${agentId}/memory`, {
        searchParams: params,
      })
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({
        queryKey: agentKeys.memory.definition(vars.agentId),
      })
      toast.success("Memory cleared")
    },
  })
}
