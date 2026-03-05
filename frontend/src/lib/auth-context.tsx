import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react"
import { api, parseApiError, setAccessToken as setApiClientToken } from "./api-client"

interface AuthUser {
  id: string
  email: string
  display_name: string | null
  email_verified: boolean
  is_active: boolean
  tenant_id: string
  role: string | null
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
  const [isLoading, setIsLoading] = useState(false)

  // Keep api-client in sync whenever React state changes
  useEffect(() => {
    setApiClientToken(accessToken)
  }, [accessToken])

  const login = useCallback(async (email: string, password: string) => {
    setIsLoading(true)
    try {
      const res = await api.post("auth/login", { json: { email, password }, credentials: "include" }).json<{
        access_token: string
        user: AuthUser
      }>()
      syncToken(res.access_token, _setAccessToken)
      setUser(res.user)
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
          .json<{ access_token: string; user: AuthUser }>()
        syncToken(res.access_token, _setAccessToken)
        setUser(res.user)
        window.dispatchEvent(new Event("auth-change"))
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
