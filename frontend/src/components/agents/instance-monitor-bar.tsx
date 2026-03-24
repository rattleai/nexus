import * as React from "react"
import { Activity, ChevronDown, ChevronUp } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import { InstanceMonitorItem } from "./instance-monitor-item"
import {
  useAllActiveInstances,
  useAgentDefinitions,
} from "@/hooks/use-agents"
import { useAgentStore } from "@/stores/agent-store"
import { cn } from "@/lib/utils"

export function InstanceMonitorBar() {
  const instanceMonitorCollapsed = useAgentStore(
    (s) => s.instanceMonitorCollapsed,
  )
  const toggleMonitorCollapsed = useAgentStore(
    (s) => s.toggleMonitorCollapsed,
  )

  const { data: instancesData } = useAllActiveInstances()
  const { data: definitionsData } = useAgentDefinitions()

  const instances = instancesData?.items ?? []
  const definitions = definitionsData?.items ?? []

  // Build a lookup from definition id to name
  const definitionNameMap = React.useMemo(() => {
    const map = new Map<string, string>()
    for (const def of definitions) {
      map.set(def.id, def.name)
    }
    return map
  }, [definitions])

  return (
    <div className="border-t bg-background shrink-0">
      {/* Header row -- always visible */}
      <div className="flex items-center justify-between px-3 py-1.5">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Activity className="h-3.5 w-3.5" />
          <span className="font-medium">
            Active Instances
          </span>
          {instances.length > 0 && (
            <span className="rounded-full bg-primary/10 text-primary px-1.5 py-0.5 text-[10px] font-semibold leading-none">
              {instances.length}
            </span>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={toggleMonitorCollapsed}
          aria-label={
            instanceMonitorCollapsed ? "Expand monitor" : "Collapse monitor"
          }
        >
          {instanceMonitorCollapsed ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </Button>
      </div>

      {/* Expandable instance list */}
      {!instanceMonitorCollapsed && (
        <div className="px-3 pb-2">
          {instances.length === 0 ? (
            <div className="flex items-center justify-center py-2">
              <span className="text-xs text-muted-foreground">
                No active instances
              </span>
            </div>
          ) : (
            <ScrollArea className="w-full" type="scroll">
              <div className="flex items-center gap-2 pb-1">
                {instances.map((instance, idx) => (
                  <InstanceMonitorItem
                    key={instance.id}
                    instance={instance}
                    agentName={definitionNameMap.get(instance.definition_id)}
                    index={idx}
                  />
                ))}
              </div>
              <ScrollBar orientation="horizontal" />
            </ScrollArea>
          )}
        </div>
      )}
    </div>
  )
}
