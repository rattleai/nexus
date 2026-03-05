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
