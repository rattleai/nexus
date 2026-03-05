export interface HealthResponse {
  status: "ok" | "degraded"
  version: string
  services: Record<string, boolean>
}

export interface ErrorResponse {
  detail: string
  code?: string
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
