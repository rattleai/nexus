import * as React from "react"
import {
  ArrowLeft,
  CheckCircle,
  XCircle,
  Loader2,
  Clock,
  Square,
  Pause,
  Zap,
  DollarSign,
  Copy,
  Hash,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { formatDateTime, formatRelativeTime } from "@/lib/format"
import { useStopInstance } from "@/hooks/use-agents"
import { toast } from "sonner"
import type { AgentInstance } from "@/types/agents"

interface RunDetailViewProps {
  instance: AgentInstance
  onBack: () => void
}

const statusConfig: Record<
  string,
  { icon: React.ElementType; color: string; bg: string; label: string }
> = {
  pending: { icon: Clock, color: "text-slate-500", bg: "bg-slate-100 dark:bg-slate-800", label: "Pending" },
  running: { icon: Loader2, color: "text-blue-500", bg: "bg-blue-50 dark:bg-blue-950", label: "Running" },
  completed: { icon: CheckCircle, color: "text-emerald-500", bg: "bg-emerald-50 dark:bg-emerald-950", label: "Completed" },
  failed: { icon: XCircle, color: "text-red-500", bg: "bg-red-50 dark:bg-red-950", label: "Failed" },
  cancelled: { icon: Square, color: "text-gray-500", bg: "bg-gray-100 dark:bg-gray-800", label: "Cancelled" },
  paused: { icon: Pause, color: "text-amber-500", bg: "bg-amber-50 dark:bg-amber-950", label: "Paused" },
}

export function RunDetailView({ instance, onBack }: RunDetailViewProps) {
  const config = statusConfig[instance.status] ?? statusConfig.pending
  const Icon = config.icon
  const stopInstance = useStopInstance()
  const [isStopping, setIsStopping] = React.useState(false)

  const duration = React.useMemo(() => {
    if (!instance.started_at) return null
    const start = new Date(instance.started_at).getTime()
    const end = instance.completed_at
      ? new Date(instance.completed_at).getTime()
      : Date.now()
    const seconds = (end - start) / 1000
    if (seconds < 60) return `${seconds.toFixed(1)}s`
    const totalSecs = Math.round(seconds)
    const mins = Math.floor(totalSecs / 60)
    const secs = totalSecs % 60
    return `${mins}m ${secs}s`
  }, [instance.started_at, instance.completed_at])

  const handleStop = () => {
    setIsStopping(true)
    stopInstance.mutate(instance.id, {
      onSettled: () => setIsStopping(false),
    })
  }

  const copyId = () => {
    navigator.clipboard.writeText(instance.id)
    toast.success("Run ID copied")
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={onBack}
          aria-label="Back to operations"
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">Run {instance.id.slice(0, 8)}</h3>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={copyId}
              aria-label="Copy run ID"
            >
              <Copy className="h-3 w-3" />
            </Button>
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            Created {formatRelativeTime(instance.created_at)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {instance.status === "running" && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs text-red-500 border-red-200 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
              onClick={handleStop}
              disabled={isStopping}
            >
              {isStopping ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Square className="h-3 w-3 mr-1" />}
              Stop
            </Button>
          )}
        </div>
      </div>

      {/* Status banner */}
      <div className={cn("rounded-xl p-4 flex items-center gap-3", config.bg)}>
        <div className={cn("flex h-10 w-10 items-center justify-center rounded-lg bg-background/80")}>
          <Icon
            className={cn(
              "h-5 w-5",
              config.color,
              instance.status === "running" && "animate-spin",
            )}
          />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <p className={cn("text-sm font-medium", config.color)}>{config.label}</p>
            {instance.status === "running" && (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2 py-0.5">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-blue-500" />
                </span>
                <span className="text-[10px] font-medium text-blue-600 dark:text-blue-400">Live</span>
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {instance.started_at
              ? `Started ${formatDateTime(instance.started_at)}`
              : "Waiting to start"}
            {instance.completed_at && ` — Finished ${formatDateTime(instance.completed_at)}`}
          </p>
        </div>
        {duration && (
          <div className="text-right shrink-0">
            <p className="text-lg font-semibold tabular-nums">{duration}</p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Duration</p>
          </div>
        )}
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-3 gap-3">
        <MetricPill icon={Hash} label="Steps" value={String(instance.steps_executed)} />
        <MetricPill
          icon={Zap}
          label="Tokens"
          value={(instance.tokens_used ?? 0).toLocaleString()}
        />
        <MetricPill
          icon={DollarSign}
          label="Cost"
          value={`$${(instance.cost_usd ?? 0).toFixed(4)}`}
        />
      </div>

      {/* Input / Output / Error sections */}
      {instance.input_data && Object.keys(instance.input_data).length > 0 && (
        <DataSection title="Input" data={instance.input_data} />
      )}

      {instance.output_data && Object.keys(instance.output_data).length > 0 && (
        <DataSection title="Output" data={instance.output_data} />
      )}

      {instance.error && (
        <Card className="border-red-200 dark:border-red-800">
          <CardContent className="p-4">
            <p className="text-xs font-medium text-red-500 mb-2">Error</p>
            <pre className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words">
              {instance.error}
            </pre>
          </CardContent>
        </Card>
      )}

      {/* Step trace */}
      <StepTrace instance={instance} />

      {/* Timeline */}
      <RunTimeline instance={instance} />
    </div>
  )
}

// ── Sub-components ──

function MetricPill({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ElementType
  label: string
  value: string
}) {
  return (
    <div className="flex items-center gap-2.5 rounded-lg border p-3">
      <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
      <div>
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</p>
        <p className="text-sm font-semibold tabular-nums">{value}</p>
      </div>
    </div>
  )
}

function DataSection({
  title,
  data,
}: {
  title: string
  data: Record<string, unknown>
}) {
  const [expanded, setExpanded] = React.useState(false)
  const json = JSON.stringify(data, null, 2)
  const isLong = json.length > 300

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-medium text-muted-foreground">{title}</p>
          {isLong && (
            <Button
              variant="ghost"
              size="sm"
              className="h-5 text-[10px] px-2"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? "Collapse" : "Expand"}
            </Button>
          )}
        </div>
        <pre
          className={cn(
            "text-xs bg-muted/50 rounded-lg p-3 overflow-x-auto",
            !expanded && isLong && "max-h-24 overflow-hidden relative",
          )}
        >
          {json}
          {!expanded && isLong && (
            <div className="absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-muted/50 to-transparent" />
          )}
        </pre>
      </CardContent>
    </Card>
  )
}

function StepTrace({ instance }: { instance: AgentInstance }) {
  if (instance.steps_executed <= 0) return null

  // Derive steps from available data
  // The backend tracks steps_executed count. We create a visual representation
  // showing the execution flow from start to completion.
  const steps = instance.steps_executed
  const tokensPerStep = steps > 0 ? Math.round((instance.tokens_used ?? 0) / steps) : 0
  const costPerStep = steps > 0 ? (instance.cost_usd ?? 0) / steps : 0

  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium text-muted-foreground mb-3">
          Execution Trace
        </p>
        <div className="space-y-1">
          {Array.from({ length: Math.min(steps, 20) }, (_, i) => {
            const isLast = i === Math.min(steps, 20) - 1
            const isFailed = isLast && instance.status === "failed"
            return (
              <div key={i} className="flex items-center gap-2.5">
                {/* Step indicator */}
                <div className="flex flex-col items-center">
                  <span
                    className={cn(
                      "flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-bold",
                      isFailed
                        ? "bg-red-100 text-red-600 dark:bg-red-900 dark:text-red-400"
                        : "bg-primary/10 text-primary",
                    )}
                  >
                    {i + 1}
                  </span>
                  {!isLast && <span className="w-px h-2 bg-border" />}
                </div>
                {/* Step bar */}
                <div className="flex-1 flex items-center gap-2">
                  <div
                    className={cn(
                      "h-5 rounded-sm flex items-center px-2 text-[10px]",
                      isFailed
                        ? "bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400"
                        : "bg-muted text-muted-foreground",
                    )}
                    style={{ width: `${Math.max(30, Math.min(100, (tokensPerStep / Math.max((instance.tokens_used ?? 1), 1)) * steps * 100))}%` }}
                  >
                    Step {i + 1}
                  </div>
                  <span className="text-[10px] text-muted-foreground tabular-nums shrink-0">
                    ~{tokensPerStep.toLocaleString()} tok
                  </span>
                </div>
              </div>
            )
          })}
          {steps > 20 && (
            <p className="text-[11px] text-muted-foreground pl-7">
              +{steps - 20} more steps
            </p>
          )}
        </div>
        {/* Summary */}
        <div className="flex gap-4 mt-3 pt-3 border-t text-[11px] text-muted-foreground">
          <span>{steps} total steps</span>
          <span>~{tokensPerStep.toLocaleString()} tokens/step</span>
          <span>${costPerStep.toFixed(4)}/step</span>
        </div>
      </CardContent>
    </Card>
  )
}

function RunTimeline({ instance }: { instance: AgentInstance }) {
  const events: Array<{ label: string; time: string | null; status: "done" | "active" | "pending" }> = []

  events.push({
    label: "Created",
    time: instance.created_at,
    status: "done",
  })

  if (instance.started_at) {
    events.push({
      label: "Started",
      time: instance.started_at,
      status: "done",
    })
  }

  if (instance.status === "running") {
    events.push({
      label: "In Progress",
      time: null,
      status: "active",
    })
  }

  if (instance.completed_at) {
    events.push({
      label: instance.status === "completed" ? "Completed" : instance.status === "failed" ? "Failed" : "Finished",
      time: instance.completed_at,
      status: "done",
    })
  } else if (instance.status !== "running" && instance.status !== "pending") {
    events.push({
      label: instance.status.charAt(0).toUpperCase() + instance.status.slice(1),
      time: instance.updated_at,
      status: "done",
    })
  }

  if (events.length <= 1) return null

  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium text-muted-foreground mb-3">Timeline</p>
        <div className="space-y-0">
          {events.map((event, i) => (
            <div key={i} className="flex items-start gap-3">
              {/* Dot + line */}
              <div className="flex flex-col items-center pt-0.5">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full shrink-0",
                    event.status === "done" && "bg-emerald-500",
                    event.status === "active" && "bg-blue-500 animate-pulse",
                    event.status === "pending" && "bg-muted-foreground/30",
                  )}
                />
                {i < events.length - 1 && (
                  <span className="w-px flex-1 bg-border min-h-[20px]" />
                )}
              </div>
              {/* Content */}
              <div className="pb-3">
                <p className="text-xs font-medium">{event.label}</p>
                {event.time && (
                  <p className="text-[11px] text-muted-foreground">
                    {formatDateTime(event.time)}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
