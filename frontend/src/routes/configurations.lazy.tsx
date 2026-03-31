import { createLazyFileRoute, Outlet } from "@tanstack/react-router"
import { AuthGuard } from "@/components/auth/auth-guard"

export const Route = createLazyFileRoute("/configurations")({
  component: ConfigurationsLayout,
})

function ConfigurationsLayout() {
  return (
    <AuthGuard>
      <Outlet />
    </AuthGuard>
  )
}
