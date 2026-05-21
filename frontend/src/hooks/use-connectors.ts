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
  source: "yaml" | "plugin" | "composio" | "tenant_mcp"
  is_system: boolean
  is_active: boolean
  version: string
  documentation_url: string | null
  tags: string[] | null
  tool_definitions: Record<string, unknown>[] | null
  aliases: string[] | null
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

// ── App Credentials (OAuth app registration per tenant) ────────────

export interface AppCredentialsStatus {
  connector_slug: string
  is_registered: boolean
  client_id_preview: string | null
  redirect_uri_override: string | null
  has_webhook_secret: boolean
  created_at: string | null
  updated_at: string | null
}

export function useAppCredentialsStatus(slug: string) {
  return useQuery({
    queryKey: ["connectors", "app-credentials", slug],
    queryFn: ({ signal }) =>
      api
        .get(`connectors/${slug}/app-credentials`, { signal })
        .json<AppCredentialsStatus>(),
    enabled: !!slug,
  })
}

export function useRegisterAppCredentials() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      slug,
      body,
    }: {
      slug: string
      body: {
        client_id: string
        client_secret: string
        webhook_secret?: string
        redirect_uri_override?: string
      }
    }) =>
      api
        .post(`connectors/${slug}/app-credentials`, { json: body })
        .json<AppCredentialsStatus>(),
    onSuccess: (_data, { slug }) =>
      qc.invalidateQueries({ queryKey: ["connectors", "app-credentials", slug] }),
  })
}

export function useDeleteAppCredentials() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slug: string) =>
      api.delete(`connectors/${slug}/app-credentials`),
    onSuccess: (_data, slug) =>
      qc.invalidateQueries({ queryKey: ["connectors", "app-credentials", slug] }),
  })
}

// ── Dynamic Client Registration (RFC 7591) ─────────────────────────

export interface DynamicClientRegisterResult {
  client_id: string
  registration_endpoint: string
  authorize_url: string
  token_url: string
  scopes_supported: string[] | null
}

export function useRegisterOAuthClient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      slug,
      body,
    }: {
      slug: string
      body: { client_name: string; redirect_uris: string[] }
    }) =>
      api
        .post(`connectors/${slug}/register-client`, { json: body })
        .json<DynamicClientRegisterResult>(),
    onSuccess: (_data, { slug }) =>
      qc.invalidateQueries({ queryKey: ["connectors", "app-credentials", slug] }),
  })
}

// ── Refresh MCP tool discovery ─────────────────────────────────────

export function useRefreshConnectionTools() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      api.post(`connections/${id}/refresh-tools`).json<ConnectionTool[]>(),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: queryKeys.connections.tools(id) })
      qc.invalidateQueries({ queryKey: queryKeys.connections.detail(id) })
    },
  })
}
