import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"

// ── Types ───────────────────────────────────────────────

export interface ConnectorDefinition {
  id: string
  slug: string
  name: string
  description: string
  icon: string
  category: string
  connector_type: string
  auth_type: string
  is_system: boolean
  is_active: boolean
  version: string
  documentation_url: string | null
  tags: string[] | null
  tool_definitions: Record<string, unknown>[] | null
  created_at: string
  updated_at: string
}

export interface TenantConnection {
  id: string
  tenant_id: string
  connector_definition_id: string
  display_name: string
  account_identifier: string | null
  status: string
  status_message: string | null
  connector_slug: string | null
  connector_name: string | null
  connector_icon: string | null
  connector_type: string | null
  tools_count: number
  resources_count: number
  health_status: Record<string, unknown> | null
  health_checked_at: string | null
  cache_refreshed_at: string | null
  config_overrides: Record<string, unknown> | null
  last_used_at: string | null
  created_at: string
  updated_at: string
}

export interface ConnectionTool {
  name: string
  description: string
  input_schema: Record<string, unknown> | null
}

export interface ConnectionTestResult {
  status: string
  message: string
  latency_ms: number | null
}

interface ListResponse<T> {
  items: T[]
  total: number
}

// ── Connector catalog queries ───────────────────────────

export function useConnectors(category?: string) {
  return useQuery({
    queryKey: queryKeys.connectors.list(category),
    queryFn: ({ signal }) => {
      const params = category ? `?category=${category}` : ""
      return api.get(`connectors${params}`, { signal }).json<ListResponse<ConnectorDefinition>>()
    },
  })
}

export function useConnector(slug: string) {
  return useQuery({
    queryKey: queryKeys.connectors.detail(slug),
    queryFn: ({ signal }) =>
      api.get(`connectors/${slug}`, { signal }).json<ConnectorDefinition>(),
    enabled: !!slug,
  })
}

// ── Connection queries ──────────────────────────────────

export function useConnections() {
  return useQuery({
    queryKey: queryKeys.connections.list(),
    queryFn: ({ signal }) =>
      api.get("connections", { signal }).json<ListResponse<TenantConnection>>(),
  })
}

export function useConnection(id: string) {
  return useQuery({
    queryKey: queryKeys.connections.detail(id),
    queryFn: ({ signal }) =>
      api.get(`connections/${id}`, { signal }).json<TenantConnection>(),
    enabled: !!id,
  })
}

export function useConnectionTools(id: string) {
  return useQuery({
    queryKey: queryKeys.connections.tools(id),
    queryFn: ({ signal }) =>
      api.get(`connections/${id}/tools`, { signal }).json<ConnectionTool[]>(),
    enabled: !!id,
  })
}

// ── Connection mutations ────────────────────────────────

export function useCreateConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      connector_slug: string
      display_name: string
      api_key?: string
      bearer_token?: string
    }) => api.post("connections", { json: body }).json<TenantConnection>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.connections.all }),
  })
}

export function useDeleteConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`connections/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.connections.all }),
  })
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (id: string) =>
      api.post(`connections/${id}/test`).json<ConnectionTestResult>(),
  })
}

export function useStartOAuth() {
  return useMutation({
    mutationFn: (slug: string) =>
      api.post(`connectors/${slug}/auth/start`).json<{ auth_url: string; state: string }>(),
  })
}

export function useRegisterMCPServer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { url: string; name: string; description?: string }) =>
      api.post("connectors/register-mcp", { json: body }).json<ConnectorDefinition>(),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.connectors.all }),
  })
}
