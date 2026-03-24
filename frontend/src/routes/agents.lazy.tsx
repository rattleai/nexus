import { createLazyFileRoute, Outlet } from "@tanstack/react-router"
import { AuthGuard } from "@/components/auth/auth-guard"

export const Route = createLazyFileRoute("/agents")({
  component: AgentsLayout,
})

function AgentsLayout() {
  return (
    <AuthGuard>
      <Outlet />
    </AuthGuard>
  )
}
