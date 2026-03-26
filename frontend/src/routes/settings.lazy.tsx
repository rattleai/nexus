import { createLazyFileRoute, Outlet } from "@tanstack/react-router"
import { AuthGuard } from "@/components/auth/auth-guard"

export const Route = createLazyFileRoute("/settings")({
  component: SettingsLayout,
})

function SettingsLayout() {
  return (
    <AuthGuard>
      <Outlet />
    </AuthGuard>
  )
}
