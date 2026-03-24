import * as React from "react"
import {
  Activity,
  Zap,
  DollarSign,
  Footprints,
  Loader2,
  AlertCircle,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import {
  useAgentDefinitions,
  useAllActiveInstances,
  useAgentAnalytics,
} from "@/hooks/use-agents"
import { cn } from "@/lib/utils"
import { ConcurrencyGauge } from "./concurrency-gauge"
import { ExecutionTimeline } from "./execution-timeline"
import { ActivityFeed } from "./activity-feed"
import type { AgentDefinition, AgentInstance } from "@/types/agents"

// ── Stat card ────────────────────────────────────────────────────

function DashboardStat({
  icon: Icon,
  label,
  value,
  trend,
  className,
}: {
  icon: React.ElementType
  label: string
  value: string
  trend?: string
  className?: string
}) {
  return (
    <Card className={cn("overflow-hidden", className)}>
      <CardContent className="p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted shrink-0">
            <Icon className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{label}</p>
            <div className="flex items-baseline gap-1.5">
              <p className="text-lg font-bold leading-tight truncate">
                {value}
              </p>
              {trend && (
                <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                  {trend}
                </span>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Helpers ──────────────────────────────────────────────────────

function buildAgentNameMap(
  definitions: AgentDefinition[],
): Record<string, string> {
  const map: Record<string, string> = {}
  for (const def of definitions) {
    map[def.id] = def.name
  }
  return map
}

function groupInstancesByDefinition(
  instances: AgentInstance[],
): Record<string, { running: number; pending: number }> {
  const map: Record<string, { running: number; pending: number }> = {}
  for (const inst of instances) {
    if (!map[inst.definition_id]) {
      map[inst.definition_id] = { running: 0, pending: 0 }
    }
    if (inst.status === "running") {
      map[inst.definition_id].running++
    } else if (inst.status === "pending") {
      map[inst.definition_id].pending++
    }
  }
  return map
}

// ── Main dashboard ───────────────────────────────────────────────

export function ConcurrencyDashboard() {
  const {
    data: defsData,
    isLoading: defsLoading,
    error: defsError,
  } = useAgentDefinitions("active")

  const {
    data: instancesData,
    isLoading: instancesLoading,
    error: instancesError,
  } = useAllActiveInstances()

  const {
    data: analytics,
    isLoading: analyticsLoading,
  } = useAgentAnalytics(7) // Last 7 days for dashboard stats

  const definitions = defsData?.items ?? []
  const instances = instancesData?.items ?? []

  const agentNames = React.useMemo(
    () => buildAgentNameMap(definitions),
    [definitions],
  )

  const instancesByDef = React.useMemo(
    () => groupInstancesByDefinition(instances),
    [instances],
  )

  // Definitions worth showing a gauge for: either has instances or has a concurrency limit
  const gaugeDefinitions = React.useMemo(() => {
    return definitions.filter(
      (def) =>
        def.max_concurrent_instances > 0 ||
        instancesByDef[def.id] !== undefined,
    )
  }, [definitions, instancesByDef])

  // Summary stats
  const totalActive = instances.filter(
    (i) => i.status === "running" || i.status === "pending",
  ).length
  const totalTokens = analytics?.total_tokens ?? 0
  const totalCost = analytics?.total_cost_usd ?? 0
  const avgSteps = analytics?.avg_steps_per_run ?? 0

  const isLoading = defsLoading || instancesLoading
  const hasError = defsError || instancesError

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (hasError) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2">
        <AlertCircle className="h-8 w-8 text-red-500" />
        <p className="text-sm font-medium text-red-500">
          Failed to load dashboard data
        </p>
        <p className="text-xs text-muted-foreground">
          {hasError instanceof Error ? hasError.message : "Unknown error"}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-4">
      {/* Top row: Summary stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 shrink-0">
        <DashboardStat
          icon={Activity}
          label="Active Instances"
          value={String(totalActive)}
          trend={
            instances.filter((i) => i.status === "pending").length > 0
              ? `${instances.filter((i) => i.status === "pending").length} pending`
              : undefined
          }
        />
        <DashboardStat
          icon={Zap}
          label="Total Tokens (7d)"
          value={
            totalTokens > 1_000_000
              ? `${(totalTokens / 1_000_000).toFixed(1)}M`
              : totalTokens > 1_000
                ? `${(totalTokens / 1_000).toFixed(1)}k`
                : String(totalTokens)
          }
          trend={analyticsLoading ? "loading..." : undefined}
        />
        <DashboardStat
          icon={DollarSign}
          label="Total Cost (7d)"
          value={`$${totalCost.toFixed(2)}`}
          trend={
            analytics && analytics.total_runs > 0
              ? `$${analytics.avg_cost_per_run.toFixed(3)}/run`
              : undefined
          }
        />
        <DashboardStat
          icon={Footprints}
          label="Avg Steps/Run"
          value={avgSteps.toFixed(1)}
          trend={
            analytics
              ? `${analytics.total_runs} total runs`
              : undefined
          }
        />
      </div>

      {/* Middle: Concurrency gauges grid */}
      {gaugeDefinitions.length > 0 && (
        <div className="shrink-0">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-1">
            Agent Concurrency
          </h3>
          <div className="flex flex-wrap gap-3">
            {gaugeDefinitions.map((def) => {
              const counts = instancesByDef[def.id] ?? {
                running: 0,
                pending: 0,
              }
              return (
                <ConcurrencyGauge
                  key={def.id}
                  agentId={def.id}
                  agentName={def.name}
                  runningCount={counts.running}
                  pendingCount={counts.pending}
                  maxInstances={def.max_concurrent_instances}
                />
              )
            })}
          </div>
        </div>
      )}

      {/* Bottom split: Timeline + Activity Feed */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3 flex-1 min-h-[300px]">
        {/* Execution Timeline (60%) */}
        <Card className="lg:col-span-3 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b shrink-0">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Execution Timeline
            </h3>
          </div>
          <CardContent className="p-0 flex-1 min-h-0">
            <ExecutionTimeline
              instances={instances}
              agentNames={agentNames}
            />
          </CardContent>
        </Card>

        {/* Activity Feed (40%) */}
        <Card className="lg:col-span-2 overflow-hidden flex flex-col relative">
          <CardContent className="p-0 flex-1 min-h-0">
            <ActivityFeed agentNames={agentNames} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
