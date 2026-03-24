import { AgentWorkspace } from "./agent-workspace"
import { MultiStreamView } from "./multi-stream-view"
import { ConcurrencyDashboard } from "./concurrency-dashboard"
import { InstanceDetailDrawer } from "./instance-detail-drawer"
import { WorkspaceToolbar } from "./workspace-toolbar"
import { InstanceMonitorBar } from "./instance-monitor-bar"
import { useAgentStore } from "@/stores/agent-store"

export function AgentWorkspaceShell() {
  const workspaceMode = useAgentStore((s) => s.workspaceMode)
  const drawerInstanceId = useAgentStore((s) => s.drawerInstanceId)

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Toolbar */}
      <WorkspaceToolbar />

      {/* Main workspace area */}
      <div className="flex-1 min-h-0">
        {workspaceMode === "single" && <AgentWorkspace />}
        {workspaceMode === "multi-stream" && <MultiStreamView />}
        {workspaceMode === "dashboard" && <ConcurrencyDashboard />}
      </div>

      {/* Monitor bar -- always visible */}
      <InstanceMonitorBar />

      {/* Instance detail drawer -- rendered when open */}
      {drawerInstanceId && <InstanceDetailDrawer />}
    </div>
  )
}
