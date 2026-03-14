import type { ReactNode } from "react"
import { useAuth } from "@/hooks/use-auth"
import { useAuthContext } from "@/lib/auth-context"
import { ApiKeyPrompt } from "@/components/auth/api-key-prompt"
import type { TeamRole } from "@/types/api"

interface AuthGuardProps {
  children: ReactNode
  requiredRole?: TeamRole
  fallback?: ReactNode
}

const ROLE_HIERARCHY: Record<TeamRole, number> = {
  owner: 4,
  admin: 3,
  member: 2,
  viewer: 1,
}

export function AuthGuard({
  children,
  requiredRole,
  fallback,
}: AuthGuardProps) {
  const { isAuthenticated: isApiKeyAuth } = useAuth()
  const { isAuthenticated: isJwtAuth, isLoading, user } = useAuthContext()

  // While session is being restored (refresh in flight), don't flash the login prompt.
  // This prevents the ApiKeyPrompt from appearing briefly on page load / tab refocus.
  if (isLoading) {
    return null
  }

  if (!isJwtAuth && !isApiKeyAuth) {
    return <>{fallback ?? <ApiKeyPrompt />}</>
  }

  if (requiredRole && user?.role) {
    const userLevel = ROLE_HIERARCHY[user.role as TeamRole] ?? 0
    const requiredLevel = ROLE_HIERARCHY[requiredRole]
    if (userLevel < requiredLevel) {
      return (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <h2 className="text-lg font-semibold">Access Denied</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            You need {requiredRole} access or higher to view this page.
          </p>
        </div>
      )
    }
  }

  return <>{children}</>
}
