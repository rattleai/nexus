import { createLazyFileRoute } from "@tanstack/react-router"
import { PageHeader } from "@/components/page-header"
import { AgentWorkspaceShell } from "@/components/agents/agent-workspace-shell"

export const Route = createLazyFileRoute("/settings/agents")({
  component: SettingsAgentsPage,
})

function SettingsAgentsPage() {
  return (
    <div className="flex flex-col flex-1 min-h-0 gap-4">
      <PageHeader title="Agent Workspace" />
      <AgentWorkspaceShell />
    </div>
  )
}
