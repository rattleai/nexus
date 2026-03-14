import { createRootRoute, Link, Outlet, type ErrorComponentProps } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { AppShell } from "@/components/layout/app-shell"
import { Button } from "@/components/ui/button"
import { Toaster } from "sonner"
import { useIsMobile } from "@/hooks/use-mobile"
import { OfflineBanner } from "@/components/layout/offline-banner"

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

  return (
    <AppShell>
      <OfflineBanner />
      <Outlet />
      <Toaster
        position={isMobile ? "bottom-center" : "top-right"}
        richColors
        closeButton
        offset={isMobile ? "calc(4rem + var(--safe-area-bottom, 0px))" : undefined}
      />
    </AppShell>
  )
}
