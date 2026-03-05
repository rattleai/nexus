import ky, { HTTPError } from "ky"
import { toast } from "sonner"
import { AUTH_STORAGE_KEY, JWT_STORAGE_KEY } from "./constants"

export interface ApiError {
  detail: string
  code?: string
  errors?: Array<{ field: string; message: string; type: string }>
}

/**
 * Set the in-memory JWT access token for Bearer auth.
 * Stored in a module-level variable (not localStorage) for security.
 */
let _accessToken: string | null = null

export function setAccessToken(token: string | null) {
  _accessToken = token
}

export function getAccessToken(): string | null {
  return _accessToken
}

export const api = ky.create({
  prefixUrl: "/api/v1",
  timeout: 30_000,
  credentials: "include",
  retry: {
    limit: 2,
    methods: ["get"],
    statusCodes: [408, 502, 503, 504],
    backoffLimit: 3000,
  },
  hooks: {
    beforeRequest: [
      (request) => {
        // Prefer JWT Bearer token if available
        if (_accessToken) {
          request.headers.set("Authorization", `Bearer ${_accessToken}`)
          return
        }
        // Fall back to API key auth
        try {
          const apiKey = localStorage.getItem(AUTH_STORAGE_KEY)
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
