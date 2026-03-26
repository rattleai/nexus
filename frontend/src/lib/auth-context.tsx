import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import i18n from "i18next"
import { api, attemptTokenRefresh, getAccessToken, setAccessToken as setApiClientToken } from "./api-client"

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
  loginWithOAuth: (provider: string, code: string, state: string) => Promise<void>
  register: (email: string, password: string, displayName: string, tenantSlug: string) => Promise<void>
  logout: () => Promise<void>
  isAuthenticated: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [accessToken, _setAccessToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Ref tracks the latest token so the auth-change listener never uses a stale closure
  const tokenRef = useRef(accessToken)
  tokenRef.current = accessToken

  /** Update React state, api-client, and the ref in one shot. */
  const syncToken = useCallback((token: string | null) => {
    tokenRef.current = token
    _setAccessToken(token)
    setApiClientToken(token)
  }, [])

  // Sync React auth state when the api-client's token changes externally
  // (e.g. after silent refresh via afterResponse hook, or when an invalid
  // API key is detected and cleared). Uses a ref for comparison so the
  // listener is registered once and never churns.
  useEffect(() => {
    const handleAuthChange = () => {
      const currentToken = getAccessToken()
      if (currentToken !== tokenRef.current) {
        tokenRef.current = currentToken
        _setAccessToken(currentToken)
        if (!currentToken) {
          setUser(null)
        }
      }
    }
    window.addEventListener("auth-change", handleAuthChange)
    return () => window.removeEventListener("auth-change", handleAuthChange)
  }, [])

  // Restore session on mount via refresh token cookie.
  // Uses attemptTokenRefresh() for coalescing — if React strict mode fires
  // this effect twice, both calls share the same in-flight refresh request.
  useEffect(() => {
    let cancelled = false

    async function restoreSession() {
      const refreshed = await attemptTokenRefresh()
      if (cancelled) return

      if (!refreshed) {
        _setAccessToken(null)
        setUser(null)
        setIsLoading(false)
        return
      }

      // Token is already set in api-client — sync to React state
      const token = getAccessToken()
      tokenRef.current = token
      _setAccessToken(token)

      // Fetch user profile with the new token
      try {
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
      syncToken(res.access_token)
      setUser(res.user)
      if (res.user.locale) {
        i18n.changeLanguage(res.user.locale)
      }
      window.dispatchEvent(new Event("auth-change"))
    } finally {
      setIsLoading(false)
    }
  }, [syncToken])

  const loginWithOAuth = useCallback(async (provider: string, code: string, state: string) => {
    setIsLoading(true)
    try {
      const res = await api
        .post(`auth/oauth/${provider}/callback`, { json: { code, state }, credentials: "include" })
        .json<{ access_token: string; user: AuthUser }>()
      syncToken(res.access_token)
      setUser(res.user)
      if (res.user.locale) {
        i18n.changeLanguage(res.user.locale)
      }
      window.dispatchEvent(new Event("auth-change"))
    } finally {
      setIsLoading(false)
    }
  }, [syncToken])

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
          syncToken(res.access_token)
          if (res.user) setUser(res.user)
          window.dispatchEvent(new Event("auth-change"))
        }
      } finally {
        setIsLoading(false)
      }
    },
    [syncToken],
  )

  const logout = useCallback(async () => {
    try {
      await api.post("auth/logout", { credentials: "include" })
    } catch {
      // ignore logout errors
    }
    syncToken(null)
    setUser(null)
    window.dispatchEvent(new Event("auth-change"))
  }, [syncToken])

  const value = useMemo(
    () => ({
      user,
      accessToken,
      isLoading,
      login,
      loginWithOAuth,
      register,
      logout,
      isAuthenticated: !!accessToken,
    }),
    [user, accessToken, isLoading, login, loginWithOAuth, register, logout],
  )

  return (
    <AuthContext.Provider value={value}>
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
