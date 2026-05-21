import * as React from "react"
import {
  Activity,
  CheckCircle,
  XCircle,
  Loader2,
  Clock,
  Square,
  Pause,
  RefreshCw,
  Eye,
  ExternalLink,
  MonitorPlay,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useAgentInstances, useStopInstance } from "@/hooks/use-agents"
import { useAgentStore } from "@/stores/agent-store"
import { useNavigate } from "@tanstack/react-router"
import { cn } from "@/lib/utils"
import type { AgentDefinition, AgentInstance } from "@/types/agents"

interface AgentRunsPanelProps {
  agent: AgentDefinition
}

const statusConfig: Record<
  string,
  { icon: React.ElementType; color: string; bg: string }
> = {
  pending: { icon: Clock, color: "text-muted-foreground", bg: "bg-muted" },
  running: { icon: Loader2, color: "text-blue-500", bg: "bg-blue-500/10" },
  completed: { icon: CheckCircle, color: "text-emerald-500", bg: "bg-emerald-500/10" },
  failed: { icon: XCircle, color: "text-red-500", bg: "bg-red-500/10" },
  cancelled: { icon: Square, color: "text-muted-foreground", bg: "bg-muted" },
  paused: { icon: Pause, color: "text-amber-500", bg: "bg-amber-500/10" },
}

export function AgentRunsPanel({ agent }: AgentRunsPanelProps) {
  const [statusFilter, setStatusFilter] = React.useState<string>("all")
  const [stoppingIds, setStoppingIds] = React.useState<Set<string>>(new Set())
  const { data, isLoading, refetch } = useAgentInstances(
    agent.id,
    statusFilter !== "all" ? statusFilter : undefined,
  )
  const stopInstance = useStopInstance()

  const handleStop = (instanceId: string) => {
    setStoppingIds((prev) => new Set(prev).add(instanceId))
    stopInstance.mutate(instanceId, {
      onSettled: () => {
        setStoppingIds((prev) => {
          const next = new Set(prev)
          next.delete(instanceId)
          return next
        })
      },
    })
  }

  const instances = data?.items ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Activity className="h-5 w-5 text-primary" />
            Run History
          </h3>
          <p className="text-sm text-muted-foreground mt-0.5">
            {data?.total ?? 0} total runs
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-36 h-8 text-xs">
              <SelectValue placeholder="Filter" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
              <SelectItem value="running">Running</SelectItem>
              <SelectItem value="completed">Completed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
              <SelectItem value="paused">Paused</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            aria-label="Refresh runs"
            onClick={() => refetch()}
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : instances.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-center">
            <Activity className="h-10 w-10 text-muted-foreground/50 mb-3" />
            <p className="text-sm text-muted-foreground">
              No runs yet. Start a conversation in the Chat tab to create your
              first run.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {instances.map((instance) => (
            <RunCard
              key={instance.id}
              instance={instance}
              agent={agent}
              onStop={() => handleStop(instance.id)}
              isStopping={stoppingIds.has(instance.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function RunCard({
  instance,
  agent,
  onStop,
  isStopping,
}: {
  instance: AgentInstance
  agent: AgentDefinition
  onStop: () => void
  isStopping: boolean
}) {
  const [expanded, setExpanded] = React.useState(false)
  const { openDrawer, addStreamPane } = useAgentStore()
  const navigate = useNavigate()
  const config = statusConfig[instance.status] ?? statusConfig.pending
  const Icon = config.icon

  const duration =
    instance.started_at && instance.completed_at
      ? (
          (new Date(instance.completed_at).getTime() -
            new Date(instance.started_at).getTime()) /
          1000
        ).toFixed(1) + "s"
      : instance.started_at
        ? "Running..."
        : "--"

  return (
    <div className="rounded-lg border overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="w-full flex items-center gap-3 p-3 text-left hover:bg-accent/30 transition-colors"
      >
        <div className={cn("flex h-8 w-8 items-center justify-center rounded-md shrink-0", config.bg)}>
          <Icon
            className={cn(
              "h-4 w-4",
              config.color,
              instance.status === "running" && "animate-spin",
            )}
          />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-muted-foreground">
              {instance.id.slice(0, 8)}...
            </span>
            <Badge variant="outline" className="text-xs capitalize">
              {instance.status}
            </Badge>
          </div>
          <div className="flex items-center gap-4 mt-0.5 text-xs text-muted-foreground">
            <span>{instance.steps_executed} steps</span>
            <span>{(instance.tokens_used ?? 0).toLocaleString()} tokens</span>
            <span>${(instance.cost_usd ?? 0).toFixed(4)}</span>
            <span>{duration}</span>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-muted-foreground">
            {new Date(instance.created_at).toLocaleString()}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0"
            title="View Details"
            onClick={(e) => {
              e.stopPropagation()
              openDrawer(instance.id)
            }}
          >
            <Eye className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0"
            title="Open in Sessions"
            onClick={(e) => {
              e.stopPropagation()
              navigate({ to: "/agents/$instanceId", params: { instanceId: instance.id } })
            }}
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </Button>
          {(instance.status === "running" || instance.status === "pending") && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              title="Open in Stream"
              onClick={(e) => {
                e.stopPropagation()
                addStreamPane(instance.id, agent.name, agent.id)
              }}
            >
              <MonitorPlay className="h-3.5 w-3.5" />
            </Button>
          )}
          {instance.status === "running" && (
            <Button
              variant="destructive"
              size="sm"
              className="h-7 text-xs"
              onClick={(e) => {
                e.stopPropagation()
                onStop()
              }}
              disabled={isStopping}
            >
              Stop
            </Button>
          )}
        </div>
      </button>

      {expanded && (
        <div className="border-t bg-muted/20 p-3 space-y-3">
          {instance.input_data && Object.keys(instance.input_data).length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">Input</div>
              <pre className="text-xs bg-muted rounded p-2 overflow-x-auto max-w-full max-h-40">
                {JSON.stringify(instance.input_data, null, 2)}
              </pre>
            </div>
          )}
          {instance.output_data && Object.keys(instance.output_data).length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">Output</div>
              <pre className="text-xs bg-muted rounded p-2 overflow-x-auto max-w-full max-h-40">
                {JSON.stringify(instance.output_data, null, 2)}
              </pre>
            </div>
          )}
          {instance.error && (
            <div>
              <div className="text-xs font-medium text-red-500 mb-1">Error</div>
              <pre className="text-xs bg-red-500/10 text-red-500 rounded p-2 overflow-x-auto max-w-full">
                {instance.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
