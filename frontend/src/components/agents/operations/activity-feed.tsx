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

const statusMeta: Record<
  string,
  { icon: React.ElementType; color: string; dot: string }
> = {
  pending: { icon: Clock, color: "text-muted-foreground", dot: "bg-slate-400" },
  running: { icon: Loader2, color: "text-blue-500", dot: "bg-blue-500" },
  completed: { icon: CheckCircle, color: "text-emerald-500", dot: "bg-emerald-500" },
  failed: { icon: XCircle, color: "text-red-500", dot: "bg-red-500" },
  cancelled: { icon: Square, color: "text-muted-foreground", dot: "bg-gray-400" },
  paused: { icon: Pause, color: "text-amber-500", dot: "bg-amber-500" },
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

  return (
    <div className="space-y-0.5">
      {instances.map((instance, i) => {
        const meta = statusMeta[instance.status] ?? statusMeta.pending
        const Icon = meta.icon

        return (
          <button
            key={instance.id}
            onClick={() => onSelectRun?.(instance)}
            className={cn(
              "w-full flex items-center gap-3 rounded-lg px-3 py-2.5 text-left",
              "transition-colors hover:bg-accent/50",
              onSelectRun && "cursor-pointer",
              !onSelectRun && "cursor-default",
            )}
          >
            {/* Timeline dot */}
            <div className="flex flex-col items-center shrink-0">
              <span className={cn("h-2 w-2 rounded-full", meta.dot)} />
              {i < instances.length - 1 && (
                <span className="w-px flex-1 bg-border mt-1 min-h-[12px]" />
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium">
                  Run {instance.id.slice(0, 8)}
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
              {onSelectRun && (
                <ChevronRight className="h-3 w-3 text-muted-foreground/50" />
              )}
            </div>
          </button>
        )
      })}
    </div>
  )
}
