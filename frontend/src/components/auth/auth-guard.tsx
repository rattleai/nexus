import type { ReactNode } from "react"
import { useTranslation } from "react-i18next"
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
  const { isAuthenticated } = useAuth()
  const { user } = useAuthContext()
  const { t } = useTranslation()

  if (!isAuthenticated) {
    return <>{fallback ?? <ApiKeyPrompt />}</>
  }

  if (requiredRole && user?.role) {
    const userLevel = ROLE_HIERARCHY[user.role as TeamRole] ?? 0
    const requiredLevel = ROLE_HIERARCHY[requiredRole]
    if (userLevel < requiredLevel) {
      return (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <h2 className="text-lg font-semibold">{t("error_state.access_denied")}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("error_state.access_denied_message", { role: requiredRole })}
          </p>
        </div>
      )
    }
  }

  return <>{children}</>
}
