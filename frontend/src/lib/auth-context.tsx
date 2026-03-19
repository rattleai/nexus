import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
import i18n from "i18next"
import { HTTPError } from "ky"
import { api, getAccessToken, setAccessToken as setApiClientToken } from "./api-client"

interface AuthUser {
  id: string
  email: string
  display_name: string | null
  email_verified: boolean
  is_active: boolean
  tenant_id: string
  role: string | null
  locale: string | null
  created_at: string
}

interface AuthContextValue {
  user: AuthUser | null
  accessToken: string | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName: string, tenantSlug: string) => Promise<void>
  logout: () => Promise<void>
  isAuthenticated: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

/**
 * Update both React state and api-client module-level token.
 * The api-client reads from its module-level variable for Bearer auth.
 */
function syncToken(token: string | null, setter: (t: string | null) => void) {
  setter(token)
  setApiClientToken(token)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [accessToken, _setAccessToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Keep api-client in sync whenever React state changes
  useEffect(() => {
    setApiClientToken(accessToken)
  }, [accessToken])

  // Sync React auth state when the api-client's token changes externally
  // (e.g. when attemptTokenRefresh() fails in the afterResponse hook and
  // clears the module-level _accessToken, or when an invalid API key is
  // detected and cleared). Without this, React state stays "authenticated"
  // while the actual token is null, causing persistent 401 errors.
  useEffect(() => {
    const handleAuthChange = () => {
      const currentToken = getAccessToken()
      if (currentToken !== accessToken) {
        _setAccessToken(currentToken)
        if (!currentToken) {
          setUser(null)
        }
      }
    }
    window.addEventListener("auth-change", handleAuthChange)
    return () => window.removeEventListener("auth-change", handleAuthChange)
  }, [accessToken])

  // Attempt session restoration on mount via refresh token cookie.
  // Distinguishes genuine "no session" (401) from transient errors and retries.
  useEffect(() => {
    let cancelled = false

    async function restoreSession(attempt = 0) {
      try {
        const res = await api
          .post("auth/refresh", { credentials: "include", timeout: 15_000 })
          .json<{ access_token: string }>()
        if (cancelled) return
        syncToken(res.access_token, _setAccessToken)
        // Fetch user profile with the new token
        try {
          setApiClientToken(res.access_token)
          const profile = await api.get("auth/me").json<AuthUser>()
          if (!cancelled) {
            setUser(profile)
            if (profile.locale) {
              i18n.changeLanguage(profile.locale)
            }
          }
        } catch (err) {
          console.warn("Failed to fetch user profile after token refresh:", err)
          // Token works but profile fetch failed — still authenticated
        }
        if (!cancelled) setIsLoading(false)
      } catch (err) {
        if (cancelled) return

        // 401/403 = genuinely no session (expired/missing refresh token).
        // Anything else (network error, 5xx, timeout) = transient — retry.
        const isAuthError =
          err instanceof HTTPError && (err.response.status === 401 || err.response.status === 403)

        if (!isAuthError && attempt < 2) {
          const delay = 1000 * (attempt + 1)
          console.debug(`Session restoration attempt ${attempt + 1} failed (transient), retrying in ${delay}ms`)
          setTimeout(() => {
            if (!cancelled) restoreSession(attempt + 1)
          }, delay)
          return
        }

        // Either auth error or exhausted retries
        syncToken(null, _setAccessToken)
        setUser(null)
        if (!cancelled) setIsLoading(false)
        console.debug("Session restoration failed - user not authenticated")
      }
    }

    restoreSession()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    setIsLoading(true)
    try {
      const res = await api.post("auth/login", { json: { email, password }, credentials: "include" }).json<{
        access_token: string
        user: AuthUser
      }>()
      syncToken(res.access_token, _setAccessToken)
      setUser(res.user)
      if (res.user.locale) {
        i18n.changeLanguage(res.user.locale)
      }
      window.dispatchEvent(new Event("auth-change"))
    } finally {
      setIsLoading(false)
    }
  }, [])

  const register = useCallback(
    async (email: string, password: string, displayName: string, tenantSlug: string) => {
      setIsLoading(true)
      try {
        const res = await api
          .post("auth/register", {
            json: { email, password, display_name: displayName, tenant_slug: tenantSlug },
            credentials: "include",
          })
          .json<{ access_token?: string; user?: AuthUser; message?: string }>()
        // Backend may not issue tokens (email verification required).
        // Only set auth state if an access_token was actually returned.
        if (res.access_token) {
          syncToken(res.access_token, _setAccessToken)
          if (res.user) setUser(res.user)
          window.dispatchEvent(new Event("auth-change"))
        }
      } finally {
        setIsLoading(false)
      }
    },
    [],
  )

  const logout = useCallback(async () => {
    try {
      await api.post("auth/logout", { credentials: "include" })
    } catch {
      // ignore logout errors
    }
    syncToken(null, _setAccessToken)
    setUser(null)
    window.dispatchEvent(new Event("auth-change"))
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        accessToken,
        isLoading,
        login,
        register,
        logout,
        isAuthenticated: !!accessToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuthContext() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuthContext must be used within AuthProvider")
  }
  return ctx
}
