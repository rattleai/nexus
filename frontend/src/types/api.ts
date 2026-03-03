export interface HealthResponse {
  status: "ok" | "degraded"
  version: string
  services: Record<string, boolean>
}

export interface ErrorResponse {
  detail: string
  code?: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}
