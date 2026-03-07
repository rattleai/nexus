export interface HealthResponse {
  status: "ok" | "degraded"
  version: string
  services: Record<string, boolean>
}

export interface ErrorResponse {
  detail: string
  code?: string
  request_id?: string
  errors?: Array<{ field: string; message: string; type: string }>
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface CursorPaginatedResponse<T> {
  items: T[]
  next_cursor: string | null
  has_more: boolean
}

// ── Tenant ────────────────────────────────────────────

export interface Tenant {
  id: string
  name: string
  slug: string
  plan: string
  is_active: boolean
  settings: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

// ── API Key ───────────────────────────────────────────

export interface ApiKey {
  id: string
  name: string
  rate_limit: number | null
  scopes: string[] | null
  active: boolean
  created_at: string
}

export interface ApiKeyCreated extends ApiKey {
  raw_key: string
}

// ── User / Auth ──────────────────────────────────────

export interface User {
  id: string
  email: string
  display_name: string | null
  email_verified: boolean
  is_active: boolean
  tenant_id: string
  role: string | null
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface AuthResponse extends TokenResponse {
  user: User
}

// ── Job ───────────────────────────────────────────────

export type JobStatus = "pending" | "processing" | "completed" | "failed"

export interface Job {
  id: string
  type: string
  status: JobStatus
  webhook_url: string | null
  payload: Record<string, unknown> | null
  started_at: string | null
  completed_at: string | null
  error: string | null
  result: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

// ── File ──────────────────────────────────────────────

export interface FileRecord {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  storage_path: string
  uploaded_by: string | null
  created_at: string
}

// ── Billing ───────────────────────────────────────────

export interface Plan {
  id: string
  name: string
  stripe_price_id: string | null
  price_monthly: number
  limits: Record<string, number>
  features: string[]
  is_default: boolean
}

export interface Subscription {
  id: string
  stripe_subscription_id: string | null
  status: "active" | "past_due" | "canceled" | "trialing" | "incomplete"
  plan: Plan | null
  current_period_start: string | null
  current_period_end: string | null
  cancel_at_period_end: boolean
  created_at: string
}

// ── Team ──────────────────────────────────────────────

export type TeamRole = "owner" | "admin" | "member" | "viewer"

export interface TeamMember {
  id: string
  email: string
  display_name: string | null
  role: TeamRole
  is_active: boolean
  joined_at: string
}

export interface Invitation {
  id: string
  email: string
  role: TeamRole
  invited_by: string
  expires_at: string
  created_at: string
}

// ── Webhook ───────────────────────────────────────────

export interface WebhookEndpoint {
  id: string
  url: string
  events: string[]
  active: boolean
  secret: string | null
  created_at: string
  updated_at: string
}

export interface WebhookDelivery {
  id: string
  endpoint_id: string
  event_type: string
  payload: Record<string, unknown>
  status_code: number | null
  response_body: string | null
  success: boolean
  attempts: number
  delivered_at: string | null
  created_at: string
}

// ── Notification ──────────────────────────────────────

export type NotificationType = "info" | "success" | "warning" | "error"

export interface Notification {
  id: string
  type: NotificationType
  title: string
  message: string
  read: boolean
  action_url: string | null
  created_at: string
}

// ── Audit Log ─────────────────────────────────────────

export interface AuditLog {
  id: string
  user_id: string | null
  user_email: string | null
  action: string
  resource_type: string
  resource_id: string | null
  metadata: Record<string, unknown> | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

// ── Usage ─────────────────────────────────────────────

export interface UsageMetric {
  used: number
  limit: number | null
}

export interface UsageSummary {
  jobs: UsageMetric
  api_keys: UsageMetric
  team_members: UsageMetric
  storage_bytes: UsageMetric
}
