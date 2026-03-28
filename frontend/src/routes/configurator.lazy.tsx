import { createLazyFileRoute, Outlet } from "@tanstack/react-router"
import { AuthGuard } from "@/components/auth/auth-guard"

export const Route = createLazyFileRoute("/configurator")({
  component: ConfiguratorLayout,
})

function ConfiguratorLayout() {
  return (
    <AuthGuard>
      <Outlet />
    </AuthGuard>
  )
}
