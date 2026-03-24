import * as React from "react"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useAgentStore } from "@/stores/agent-store"
import { cn } from "@/lib/utils"
import type { AgentInstance, InstanceStatus } from "@/types/agents"

interface ExecutionTimelineProps {
  instances: AgentInstance[]
  agentNames: Record<string, string> // definition_id -> name mapping
}

const statusColor: Record<InstanceStatus, string> = {
  running: "bg-blue-500",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  cancelled: "bg-muted-foreground",
  pending: "bg-amber-500",
  paused: "bg-amber-400",
}

const statusColorHover: Record<InstanceStatus, string> = {
  running: "hover:bg-blue-400",
  completed: "hover:bg-emerald-400",
  failed: "hover:bg-red-400",
  cancelled: "hover:bg-muted-foreground/80",
  pending: "hover:bg-amber-400",
  paused: "hover:bg-amber-300",
}

function formatDuration(startMs: number, endMs: number): string {
  const ms = endMs - startMs
  if (ms < 1000) return `${ms}ms`
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds}s`
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
}

export function ExecutionTimeline({
  instances,
  agentNames,
}: ExecutionTimelineProps) {
  const openDrawer = useAgentStore((s) => s.openDrawer)

  // Sort by created_at descending, take at most 20
  const sorted = React.useMemo(() => {
    return [...instances]
      .sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      )
      .slice(0, 20)
      .reverse() // oldest first so timeline reads left-to-right top-to-bottom
  }, [instances])

  if (sorted.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
        No instances to display
      </div>
    )
  }

  // Compute time range for the timeline
  const now = Date.now()
  const timeStart = new Date(sorted[0].created_at).getTime()
  const timeEnd = Math.max(
    now,
    ...sorted.map((i) =>
      i.completed_at ? new Date(i.completed_at).getTime() : now,
    ),
  )
  const totalSpan = timeEnd - timeStart || 1

  // Time axis labels
  const timeLabels = React.useMemo(() => {
    const labels: { position: number; label: string }[] = []
    const count = 5
    for (let i = 0; i <= count; i++) {
      const t = timeStart + (totalSpan * i) / count
      labels.push({
        position: (i / count) * 100,
        label: new Date(t).toLocaleTimeString(undefined, {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }),
      })
    }
    return labels
  }, [timeStart, totalSpan])

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex flex-col h-full">
        {/* Scrollable bars */}
        <div className="flex-1 overflow-y-auto space-y-1 px-2 py-1 min-h-0">
          {sorted.map((instance) => {
            const createdMs = new Date(instance.created_at).getTime()
            const endMs = instance.completed_at
              ? new Date(instance.completed_at).getTime()
              : now

            const leftPct =
              ((createdMs - timeStart) / totalSpan) * 100
            const widthPct = Math.max(
              ((endMs - createdMs) / totalSpan) * 100,
              1, // minimum 1% so bars are always visible
            )

            const agentName =
              agentNames[instance.definition_id] ??
              instance.definition_id.slice(0, 8)

            const duration = formatDuration(createdMs, endMs)

            return (
              <Tooltip key={instance.id}>
                <TooltipTrigger asChild>
                  <div className="flex items-center gap-2 h-6 group">
                    {/* Agent label */}
                    <span className="text-[10px] font-medium text-muted-foreground truncate w-20 shrink-0 text-right">
                      {agentName}
                    </span>

                    {/* Bar track */}
                    <div className="relative flex-1 h-4 rounded bg-muted/40">
                      <button
                        onClick={() => openDrawer(instance.id)}
                        className={cn(
                          "absolute top-0 h-full rounded transition-colors cursor-pointer",
                          statusColor[instance.status],
                          statusColorHover[instance.status],
                          instance.status === "running" && "animate-pulse",
                        )}
                        style={{
                          left: `${leftPct}%`,
                          width: `${Math.min(widthPct, 100 - leftPct)}%`,
                        }}
                      />
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top" className="text-xs max-w-xs">
                  <div className="space-y-0.5">
                    <div className="font-medium">
                      {agentName} -- {instance.status}
                    </div>
                    <div className="text-muted-foreground">
                      ID: {instance.id.slice(0, 12)}...
                    </div>
                    <div className="text-muted-foreground">
                      Started: {formatTime(instance.created_at)}
                    </div>
                    <div className="text-muted-foreground">
                      Duration: {duration}
                    </div>
                    <div className="text-muted-foreground">
                      {instance.steps_executed} steps,{" "}
                      {instance.tokens_used.toLocaleString()} tokens, $
                      {instance.cost_usd.toFixed(4)}
                    </div>
                  </div>
                </TooltipContent>
              </Tooltip>
            )
          })}
        </div>

        {/* Time axis */}
        <div className="relative h-5 ml-[88px] mr-2 border-t shrink-0">
          {timeLabels.map((tick, i) => (
            <span
              key={i}
              className="absolute text-[9px] text-muted-foreground -translate-x-1/2 top-0.5"
              style={{ left: `${tick.position}%` }}
            >
              {tick.label}
            </span>
          ))}
        </div>
      </div>
    </TooltipProvider>
  )
}
