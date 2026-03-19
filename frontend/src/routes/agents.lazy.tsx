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
      <div className="space-y-4">
        <PageHeader
          title="Agent Workspace"
          description="Create, configure, and manage AI agents. Press Ctrl+K to quickly find agents."
        />
        <AgentWorkspace />
      </div>
    </AuthGuard>
  )
}
