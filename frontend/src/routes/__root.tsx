import { useEffect } from "react"
import { createRootRoute, Link, Outlet, useNavigate, useRouterState, type ErrorComponentProps } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { Loader2 } from "lucide-react"
import { AppShell } from "@/components/layout/app-shell"
import { PublicLayout } from "@/components/layout/public-layout"
import { Button } from "@/components/ui/button"
import { Toaster } from "sonner"
import { useIsMobile } from "@/hooks/use-mobile"
import { OfflineBanner } from "@/components/layout/offline-banner"
import { AppCommandPalette } from "@/components/app-command-palette"
import { useAuthContext } from "@/lib/auth-context"
import { useAuth } from "@/hooks/use-auth"

const PUBLIC_ROUTES = ["/login", "/register", "/forgot-password", "/reset-password", "/verify-email", "/accept-invitation"]

function RootErrorComponent({ reset }: ErrorComponentProps) {
  const { t } = useTranslation("errors")
  const { t: tc } = useTranslation("common")
  return (
    <div role="alert" className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-md text-center space-y-4">
        <h1 className="text-2xl font-bold">{t("root_error.title")}</h1>
        <p className="text-muted-foreground">{t("root_error.description")}</p>
        <div className="flex gap-2 justify-center">
          <Button variant="outline" onClick={reset}>
            {tc("buttons.try_again")}
          </Button>
          <Button asChild>
            <Link to="/">{tc("buttons.go_home")}</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}

function NotFoundComponent() {
  const { t } = useTranslation("errors")
  const { t: tc } = useTranslation("common")
  return (
    <div className="min-h-[60vh] flex items-center justify-center p-8">
      <div className="max-w-md text-center space-y-4">
        <h1 className="text-4xl font-bold text-muted-foreground">{t("not_found.code")}</h1>
        <h2 className="text-xl font-semibold">{t("not_found.title")}</h2>
        <p className="text-muted-foreground">{t("not_found.description")}</p>
        <Button asChild>
          <Link to="/">{tc("buttons.go_home")}</Link>
        </Button>
      </div>
    </div>
  )
}

export const Route = createRootRoute({
  component: RootLayout,
  errorComponent: RootErrorComponent,
  notFoundComponent: NotFoundComponent,
})

function RootLayout() {
  const isMobile = useIsMobile()
  const { isAuthenticated: isJwt, isLoading } = useAuthContext()
  const { isAuthenticated: isApiKey } = useAuth()
  const isAuthenticated = isJwt || isApiKey
  const currentPath = useRouterState({ select: (s) => s.location.pathname })
  const navigate = useNavigate()

  const isPublicRoute = PUBLIC_ROUTES.some((r) => currentPath.startsWith(r)) || currentPath === "/"

  // Redirect authenticated users away from login/register
  useEffect(() => {
    if (!isLoading && isAuthenticated && (currentPath === "/login" || currentPath === "/register")) {
      navigate({ to: "/" })
    }
  }, [isLoading, isAuthenticated, currentPath, navigate])

  // Redirect unauthenticated users away from protected routes
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !isPublicRoute) {
      navigate({ to: "/" })
    }
  }, [isLoading, isAuthenticated, isPublicRoute, navigate])

  const toaster = (
    <Toaster
      position={isMobile ? "bottom-center" : "top-right"}
      richColors
      closeButton
      offset={isMobile ? "calc(4rem + var(--safe-area-bottom, 0px))" : undefined}
    />
  )

  // Show full-page spinner while session is restoring
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        {toaster}
      </div>
    )
  }

  if (isAuthenticated) {
    return (
      <AppShell>
        <OfflineBanner />
        <Outlet />
        <AppCommandPalette />
        {toaster}
      </AppShell>
    )
  }

  // Unauthenticated — public layout
  return (
    <PublicLayout>
      <OfflineBanner />
      <Outlet />
      {toaster}
    </PublicLayout>
  )
}
