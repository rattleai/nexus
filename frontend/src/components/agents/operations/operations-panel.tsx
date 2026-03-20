import * as React from "react"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { OperationsDashboard } from "./operations-dashboard"
import { CostAnalytics } from "./cost-analytics"
import { RunDetailView } from "./run-detail-view"
import type { AgentDefinition, AgentInstance } from "@/types/agents"

interface OperationsPanelProps {
  agent: AgentDefinition
}

type SubView = "overview" | "costs"

export function OperationsPanel({ agent }: OperationsPanelProps) {
  const [subView, setSubView] = React.useState<SubView>("overview")
  const [selectedRun, setSelectedRun] = React.useState<AgentInstance | null>(null)

  // If a run is selected, show the detail view
  if (selectedRun) {
    return (
      <RunDetailView
        instance={selectedRun}
        onBack={() => setSelectedRun(null)}
      />
    )
  }

  return (
    <div className="space-y-5">
      {/* Sub-navigation — minimal segmented control */}
      <Tabs value={subView} onValueChange={(v) => setSubView(v as SubView)}>
        <TabsList className="h-8 bg-muted/50 p-0.5">
          <TabsTrigger value="overview" className="h-7 px-3 text-xs rounded-md">
            Overview
          </TabsTrigger>
          <TabsTrigger value="costs" className="h-7 px-3 text-xs rounded-md">
            Costs & Usage
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {subView === "overview" && (
        <OperationsDashboard agent={agent} onSelectRun={setSelectedRun} />
      )}
      {subView === "costs" && (
        <CostAnalytics agent={agent} />
      )}
    </div>
  )
}
