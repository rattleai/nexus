import { createLazyFileRoute } from "@tanstack/react-router"
import { AuthGuard } from "@/components/auth/auth-guard"
import { PageHeader } from "@/components/page-header"
import { AgentWorkspace } from "@/components/agents/agent-workspace"

export const Route = createLazyFileRoute("/agents")({
  component: AgentsPage,
})

function AgentsPage() {
  return (
    <AuthGuard>
      <div className="flex flex-col flex-1 min-h-0 gap-4">
        <PageHeader
          title="Agent Workspace"
        />
        <AgentWorkspace />
      </div>
    </AuthGuard>
  )
}
