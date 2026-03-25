import { LayoutGrid, Columns3, BarChart3 } from "lucide-react"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { useAgentStore } from "@/stores/agent-store"
import { useAllActiveInstances } from "@/hooks/use-agents"
import type { WorkspaceMode } from "@/types/agents"

const MODES: {
  id: WorkspaceMode
  label: string
  icon: React.ElementType
}[] = [
  { id: "single", label: "Single", icon: LayoutGrid },
  { id: "multi-stream", label: "Multi-Stream", icon: Columns3 },
  { id: "dashboard", label: "Dashboard", icon: BarChart3 },
]

export function WorkspaceToolbar() {
  const workspaceMode = useAgentStore((s) => s.workspaceMode)
  const setWorkspaceMode = useAgentStore((s) => s.setWorkspaceMode)
  const { data: instancesData } = useAllActiveInstances()
  const activeCount = instancesData?.items?.length ?? 0

  return (
    <div className="flex items-center px-4 py-2 border-b bg-background shrink-0 overflow-hidden">
      <Tabs
        value={workspaceMode}
        onValueChange={(v) => setWorkspaceMode(v as WorkspaceMode)}
      >
        <TabsList className="h-8 bg-muted p-0.5">
          {MODES.map((mode) => {
            const Icon = mode.icon
            return (
              <TabsTrigger
                key={mode.id}
                value={mode.id}
                className="h-7 px-3 text-xs data-[state=active]:bg-background data-[state=active]:shadow-sm gap-1.5"
              >
                <Icon className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{mode.label}</span>
                <span className="sm:hidden">{mode.label === "Multi-Stream" ? "Multi" : mode.label}</span>
                {mode.id === "multi-stream" && activeCount > 0 && (
                  <Badge
                    variant="secondary"
                    className="ml-1 h-4 min-w-4 px-1 text-[10px] leading-none"
                  >
                    {activeCount}
                  </Badge>
                )}
              </TabsTrigger>
            )
          })}
        </TabsList>
      </Tabs>
    </div>
  )
}
