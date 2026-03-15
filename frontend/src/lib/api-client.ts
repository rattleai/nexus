import ky, { HTTPError } from "ky"
import i18n from "i18next"
import { toast } from "sonner"
import { AUTH_STORAGE_KEY } from "./constants"

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
let _tokenVersion = 0
let _refreshPromise: Promise<boolean> | null = null

export function setAccessToken(token: string | null) {
  _accessToken = token
  _tokenVersion++
}

export function getAccessToken(): string | null {
  return _accessToken
}

export function getTokenVersion(): number {
  return _tokenVersion
}

/**
 * Attempt to refresh the access token using the httpOnly refresh cookie.
 * Returns true if refresh succeeded, false otherwise.
 * Coalesces concurrent refresh attempts into a single request.
 */
async function attemptTokenRefresh(): Promise<boolean> {
  // Coalesce: all concurrent callers share the same in-flight promise
  if (_refreshPromise) {
    return _refreshPromise
  }

  const innerPromise = (async () => {
    try {
      const res = await ky
        .post("auth/refresh", { prefixUrl: "/api/v1", credentials: "include", timeout: 15_000 })
        .json<{ access_token: string }>()
      _accessToken = res.access_token
      _tokenVersion++
      window.dispatchEvent(new Event("auth-change"))
      return true
    } catch (err) {
      console.warn("Token refresh failed:", err instanceof Error ? err.message : String(err))
      _accessToken = null
      _tokenVersion++
      window.dispatchEvent(new Event("auth-change"))
      return false
    }
  })()

  _refreshPromise = innerPromise

  try {
    return await innerPromise
  } finally {
    // Only clear if this is still the current promise (avoids clearing a newer one)
    if (_refreshPromise === innerPromise) {
      _refreshPromise = null
    }
  }
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
        // Set Accept-Language header for locale-aware responses
        if (i18n.language) {
          request.headers.set("Accept-Language", i18n.language)
        }

        // Prefer JWT Bearer token if available
        if (_accessToken) {
          request.headers.set("Authorization", `Bearer ${_accessToken}`)
          // Tag request with token version for staleness detection in afterResponse
          ;(request as Record<string, unknown>).__tokenVersion = _tokenVersion
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
      async (request, options, response) => {
        if (response.status === 401) {
          const reqVersion = (request as Record<string, unknown>).__tokenVersion as number | undefined

          // Only handle 401 for requests that were sent with a JWT token
          if (reqVersion === undefined) return

          // If the token was already refreshed since this request was sent,
          // just retry with the new token — no need to trigger another refresh
          if (reqVersion !== _tokenVersion && _accessToken) {
            request.headers.set("Authorization", `Bearer ${_accessToken}`)
            return ky(request, options)
          }

          // Token hasn't changed — attempt a refresh
          const refreshed = await attemptTokenRefresh()
          if (refreshed && _accessToken) {
            request.headers.set("Authorization", `Bearer ${_accessToken}`)
            return ky(request, options)
          }
          // Refresh failed — let the 401 propagate
          return
        }

        if (response.status === 429) {
          const retryAfter = response.headers.get("Retry-After")
          toast.warning(i18n.t("too_many_requests"), {
            description: retryAfter
              ? i18n.t("too_many_requests_with_retry", { seconds: retryAfter })
              : i18n.t("too_many_requests_generic"),
          })
        }

        if (response.status === 403) {
          console.warn("Access forbidden - check server permissions")
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
  return { detail: error instanceof Error ? error.message : i18n.t("unexpected_error") }
}
