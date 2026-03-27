import * as React from "react"
import { Square, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useStopInstance } from "@/hooks/use-agents"
import { useAgentStore } from "@/stores/agent-store"
import { cn } from "@/lib/utils"
import type { AgentInstance, InstanceStatus } from "@/types/agents"

interface InstanceMonitorItemProps {
  instance: AgentInstance
  agentName?: string
  index: number
}

const statusDotColor: Record<InstanceStatus, string> = {
  pending: "bg-muted-foreground",
  running: "bg-blue-500",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  cancelled: "bg-muted-foreground",
  paused: "bg-amber-500",
}

export function InstanceMonitorItem({
  instance,
  agentName,
  index,
}: InstanceMonitorItemProps) {
  const [isStopping, setIsStopping] = React.useState(false)
  const openDrawer = useAgentStore((s) => s.openDrawer)
  const stopInstance = useStopInstance()

  const handleStop = (e: React.MouseEvent) => {
    e.stopPropagation()
    setIsStopping(true)
    stopInstance.mutate(instance.id, {
      onSettled: () => setIsStopping(false),
    })
  }

  const dotColor = statusDotColor[instance.status] ?? statusDotColor.pending
  const isRunning = instance.status === "running"
  const shortcutLabel = index < 9 ? index + 1 : null

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            role="button"
            tabIndex={0}
            onClick={() => openDrawer(instance.id)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") openDrawer(instance.id) }}
            className={cn(
              "flex items-center gap-2 rounded-md border px-2.5 py-1.5",
              "bg-background hover:bg-accent/50 transition-colors",
              "text-left shrink-0 max-w-[220px] cursor-pointer",
            )}
          >
            {/* Status dot */}
            <span
              className={cn(
                "h-2 w-2 rounded-full shrink-0",
                dotColor,
                isRunning && "animate-pulse",
              )}
            />

            {/* Agent name */}
            <span className="text-xs font-medium truncate max-w-[80px]">
              {agentName ?? instance.definition_id.slice(0, 8)}
            </span>

            {/* Compact metrics */}
            <span className="text-[10px] text-muted-foreground whitespace-nowrap">
              {instance.steps_executed}st
              {" / "}
              {(instance.tokens_used ?? 0).toLocaleString()}tk
              {" / "}
              ${(instance.cost_usd ?? 0).toFixed(3)}
            </span>

            {/* Stop button (only for running/pending) */}
            {(isRunning || instance.status === "pending") && (
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5 shrink-0 text-muted-foreground hover:text-destructive"
                onClick={handleStop}
                disabled={isStopping}
                aria-label="Stop instance"
              >
                {isStopping ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Square className="h-3 w-3" />
                )}
              </Button>
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs">
          <div className="space-y-0.5">
            <div className="font-medium">
              {agentName ?? "Instance"} &mdash; {instance.status}
            </div>
            <div className="text-muted-foreground">
              {instance.steps_executed} steps, {(instance.tokens_used ?? 0).toLocaleString()} tokens, ${(instance.cost_usd ?? 0).toFixed(4)}
            </div>
            {shortcutLabel && (
              <div className="text-muted-foreground">
                Cmd+{shortcutLabel} to focus
              </div>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
