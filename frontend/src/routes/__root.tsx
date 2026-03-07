import { createRootRoute, Link, Outlet, type ErrorComponentProps } from "@tanstack/react-router"
import { AppShell } from "@/components/layout/app-shell"
import { Button } from "@/components/ui/button"
import { Toaster } from "sonner"
import { useIsMobile } from "@/hooks/use-mobile"
import { OfflineBanner } from "@/components/layout/offline-banner"

function RootErrorComponent({ reset }: ErrorComponentProps) {
  return (
    <div role="alert" className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-md text-center space-y-4">
        <h1 className="text-2xl font-bold">Something went wrong</h1>
        <p className="text-muted-foreground">An unexpected error occurred. Please try again.</p>
        <div className="flex gap-2 justify-center">
          <Button variant="outline" onClick={reset}>
            Try again
          </Button>
          <Button asChild>
            <Link to="/">Go home</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}

function NotFoundComponent() {
  return (
    <div className="min-h-[60vh] flex items-center justify-center p-8">
      <div className="max-w-md text-center space-y-4">
        <h1 className="text-4xl font-bold text-muted-foreground">404</h1>
        <h2 className="text-xl font-semibold">Page not found</h2>
        <p className="text-muted-foreground">The page you're looking for doesn't exist.</p>
        <Button asChild>
          <Link to="/">Go home</Link>
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
