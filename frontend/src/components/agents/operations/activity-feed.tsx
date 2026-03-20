import * as React from "react"
import {
  CheckCircle,
  XCircle,
  Loader2,
  Clock,
  Square,
  Pause,
  ChevronRight,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { useAgentInstances } from "@/hooks/use-agents"
import { cn } from "@/lib/utils"
import { formatRelativeTime } from "@/lib/format"
import type { AgentInstance } from "@/types/agents"

interface ActivityFeedProps {
  agentId?: string
  limit?: number
  onSelectRun?: (instance: AgentInstance) => void
}

const statusDot: Record<string, string> = {
  pending: "bg-slate-400",
  running: "bg-blue-500",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  cancelled: "bg-gray-400",
  paused: "bg-amber-500",
}

export function ActivityFeed({
  agentId,
  limit = 8,
  onSelectRun,
}: ActivityFeedProps) {
  const { data, isLoading } = useAgentInstances(agentId ?? null)
  const instances = (data?.items ?? []).slice(0, limit)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (instances.length === 0) {
    return (
      <p className="text-xs text-muted-foreground text-center py-8">
        No activity yet
      </p>
    )
  }

  const isInteractive = !!onSelectRun
  const Tag = isInteractive ? "button" : "div"

  return (
    <div className="space-y-0.5" role="list" aria-label="Recent agent runs">
      {instances.map((instance, i) => {
        const dot = statusDot[instance.status] ?? statusDot.pending
        const shortId = instance.id.slice(0, 8)

        return (
          <Tag
            key={instance.id}
            role="listitem"
            aria-label={`Run ${shortId}, ${instance.status}, ${instance.steps_executed} steps`}
            {...(isInteractive
              ? { onClick: () => onSelectRun!(instance) }
              : {})}
            className={cn(
              "w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-left",
              "transition-colors",
              isInteractive && "cursor-pointer hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              !isInteractive && "cursor-default",
            )}
          >
            {/* Timeline dot */}
            <div className="flex flex-col items-center shrink-0">
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  dot,
                  instance.status === "running" && "animate-pulse",
                )}
              />
              {i < instances.length - 1 && (
                <span className="w-px flex-1 bg-border mt-1 min-h-[12px]" />
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">
                  Run {shortId}
                </span>
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[10px] px-1.5 py-0 h-4 capitalize",
                    instance.status === "completed" && "border-emerald-200 text-emerald-600 dark:border-emerald-800 dark:text-emerald-400",
                    instance.status === "failed" && "border-red-200 text-red-600 dark:border-red-800 dark:text-red-400",
                    instance.status === "running" && "border-blue-200 text-blue-600 dark:border-blue-800 dark:text-blue-400",
                  )}
                >
                  {instance.status}
                </Badge>
              </div>
              <div className="flex items-center gap-3 mt-0.5 text-[11px] text-muted-foreground">
                <span>{instance.steps_executed} steps</span>
                <span>{(instance.tokens_used ?? 0).toLocaleString()} tokens</span>
                <span>${(instance.cost_usd ?? 0).toFixed(4)}</span>
              </div>
            </div>

            {/* Time + chevron */}
            <div className="flex items-center gap-1 shrink-0">
              <span className="text-[11px] text-muted-foreground">
                {formatRelativeTime(instance.created_at)}
              </span>
              {isInteractive && (
                <ChevronRight className="h-3 w-3 text-muted-foreground/50" />
              )}
            </div>
          </Tag>
        )
      })}
    </div>
  )
}
