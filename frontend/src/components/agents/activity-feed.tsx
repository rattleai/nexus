import * as React from "react"
import { Filter } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useAllActiveInstances } from "@/hooks/use-agents"
import { useAgentStore } from "@/stores/agent-store"
import { cn } from "@/lib/utils"
import type { AgentInstance, InstanceStatus } from "@/types/agents"

type StatusFilter = "all" | "running" | "completed" | "failed"

const statusBadgeVariant: Record<
  InstanceStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  pending: "outline",
  running: "default",
  paused: "secondary",
  completed: "secondary",
  failed: "destructive",
  cancelled: "outline",
}

function formatTimestamp(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
}

function buildEventDescription(instance: AgentInstance): string {
  switch (instance.status) {
    case "pending":
      return "Instance queued"
    case "running":
      return instance.steps_executed > 0
        ? `Running (${instance.steps_executed} steps, ${instance.tokens_used.toLocaleString()} tokens)`
        : "Instance started"
    case "completed":
      return `Completed (${instance.steps_executed} steps, ${instance.tokens_used.toLocaleString()} tokens, $${instance.cost_usd.toFixed(3)})`
    case "failed":
      return `Failed: ${instance.error ?? "unknown error"}`
    case "cancelled":
      return "Instance cancelled"
    case "paused":
      return "Instance paused"
    default:
      return `Status: ${instance.status}`
  }
}

interface ActivityFeedProps {
  agentNames?: Record<string, string>
}

export function ActivityFeed({ agentNames = {} }: ActivityFeedProps) {
  const [filter, setFilter] = React.useState<StatusFilter>("all")
  const [userScrolled, setUserScrolled] = React.useState(false)
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const bottomRef = React.useRef<HTMLDivElement>(null)
  const openDrawer = useAgentStore((s) => s.openDrawer)

  const { data: instancesData } = useAllActiveInstances()
  const instances = instancesData?.items ?? []

  // Build feed items: include all active + recently finished
  const feedItems = React.useMemo(() => {
    const now = Date.now()
    const tenMinutesAgo = now - 10 * 60 * 1000

    return instances
      .filter((inst) => {
        // Keep running/pending always, keep recently completed/failed/cancelled
        const isActive = inst.status === "running" || inst.status === "pending"
        const isRecent =
          inst.updated_at && new Date(inst.updated_at).getTime() > tenMinutesAgo
        if (!isActive && !isRecent) return false

        // Apply status filter
        if (filter === "all") return true
        if (filter === "running")
          return inst.status === "running" || inst.status === "pending"
        if (filter === "completed") return inst.status === "completed"
        if (filter === "failed")
          return inst.status === "failed" || inst.status === "cancelled"
        return true
      })
      .sort(
        (a, b) =>
          new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime(),
      )
  }, [instances, filter])

  // Auto-scroll to bottom unless user has scrolled up
  React.useEffect(() => {
    if (!userScrolled) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [feedItems, userScrolled])

  const handleScroll = React.useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setUserScrolled(!isAtBottom)
  }, [])

  return (
    <div className="flex flex-col h-full">
      {/* Header with filter */}
      <div className="flex items-center justify-between px-3 py-2 border-b shrink-0">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Activity Feed
        </span>
        <div className="flex items-center gap-1.5">
          <Filter className="h-3 w-3 text-muted-foreground" />
          <Select
            value={filter}
            onValueChange={(v) => setFilter(v as StatusFilter)}
          >
            <SelectTrigger className="h-6 w-[90px] text-[10px] border-none bg-muted/50 px-2">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-xs">
                All
              </SelectItem>
              <SelectItem value="running" className="text-xs">
                Running
              </SelectItem>
              <SelectItem value="completed" className="text-xs">
                Completed
              </SelectItem>
              <SelectItem value="failed" className="text-xs">
                Failed
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Feed content */}
      <ScrollArea className="flex-1 min-h-0">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="p-2 space-y-0.5"
        >
          {feedItems.length === 0 && (
            <div className="flex items-center justify-center py-8 text-xs text-muted-foreground">
              {filter === "all"
                ? "No recent activity"
                : `No ${filter} instances`}
            </div>
          )}

          {feedItems.map((instance) => {
            const agentName =
              agentNames[instance.definition_id] ??
              instance.definition_id.slice(0, 8)

            return (
              <button
                key={instance.id}
                onClick={() => openDrawer(instance.id)}
                className={cn(
                  "flex items-start gap-2 w-full text-left rounded px-2 py-1.5",
                  "hover:bg-muted/50 transition-colors group",
                )}
              >
                {/* Timestamp */}
                <span className="text-[10px] font-mono text-muted-foreground shrink-0 pt-0.5 w-[52px]">
                  {formatTimestamp(instance.updated_at)}
                </span>

                {/* Content */}
                <div className="flex-1 min-w-0 space-y-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] font-medium truncate">
                      {agentName}
                    </span>
                    <Badge
                      variant={statusBadgeVariant[instance.status]}
                      className="h-3.5 px-1 text-[9px] leading-none shrink-0"
                    >
                      {instance.status}
                    </Badge>
                  </div>
                  <p className="text-[10px] text-muted-foreground leading-tight truncate">
                    {buildEventDescription(instance)}
                  </p>
                </div>
              </button>
            )
          })}

          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* Scroll-to-bottom indicator */}
      {userScrolled && feedItems.length > 0 && (
        <button
          onClick={() => {
            bottomRef.current?.scrollIntoView({ behavior: "smooth" })
            setUserScrolled(false)
          }}
          className={cn(
            "absolute bottom-2 left-1/2 -translate-x-1/2 z-10",
            "rounded-full bg-primary px-3 py-1 text-[10px] text-primary-foreground",
            "shadow-md hover:bg-primary/90 transition-colors",
          )}
        >
          New activity
        </button>
      )}
    </div>
  )
}
