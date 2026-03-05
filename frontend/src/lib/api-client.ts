import ky, { HTTPError } from "ky"
import { toast } from "sonner"

export interface ApiError {
  detail: string
  code?: string
  errors?: Array<{ field: string; message: string; type: string }>
}

export const api = ky.create({
  prefixUrl: "/api/v1",
  timeout: 30_000,
  retry: {
    limit: 2,
    methods: ["get"],
    statusCodes: [408, 502, 503, 504],
    backoffLimit: 3000,
  },
  hooks: {
    beforeRequest: [
      (request) => {
        try {
          const apiKey = localStorage.getItem("api-key")
          if (apiKey) {
            request.headers.set("X-API-Key", apiKey)
          }
        } catch {
          // localStorage may be unavailable (e.g. Safari private mode)
        }
      },
    ],
    afterResponse: [
      async (_request, _options, response) => {
        if (response.status === 429) {
          const retryAfter = response.headers.get("Retry-After")
          toast.warning("Too many requests", {
            description: retryAfter
              ? `Please wait ${retryAfter} seconds before trying again.`
              : "Please slow down and try again shortly.",
          })
        }
      },
    ],
  },
})

/**
 * Extract a structured error from an HTTP error response.
 */
export async function parseApiError(error: unknown): Promise<ApiError> {
  if (error instanceof HTTPError) {
    try {
      return await error.response.json()
    } catch {
      return { detail: error.message, code: `HTTP_${error.response.status}` }
    }
  }
  return { detail: error instanceof Error ? error.message : "An unexpected error occurred" }
}
