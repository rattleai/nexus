import { createLazyFileRoute, Outlet, useRouterState } from "@tanstack/react-router"
import { AuthGuard } from "@/components/auth/auth-guard"
import { SessionSidebar } from "@/components/agents/sessions/session-sidebar"
import { useIsMobile } from "@/hooks/use-mobile"

export const Route = createLazyFileRoute("/agents")({
  component: AgentsLayout,
})

function AgentsLayout() {
  const isMobile = useIsMobile()
  const router = useRouterState()
  const isIndex = router.location.pathname === "/agents" || router.location.pathname === "/agents/"

  return (
    <AuthGuard>
      {isMobile ? (
        // Mobile: show sidebar at index, show panel at /agents/$instanceId
        <div className="flex flex-col h-[calc(100vh-8rem)]">
          {isIndex ? (
            <SessionSidebar />
          ) : (
            <Outlet />
          )}
        </div>
      ) : (
        // Desktop: side-by-side layout
        <div className="flex h-[calc(100vh-8rem)] -m-4 sm:-m-6">
          <div className="w-72 border-r flex-shrink-0 overflow-hidden">
            <SessionSidebar />
          </div>
          <div className="flex-1 min-w-0 overflow-hidden">
            <Outlet />
          </div>
        </div>
      )}
    </AuthGuard>
  )
}
