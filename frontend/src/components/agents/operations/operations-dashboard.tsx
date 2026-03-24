import * as React from "react"
import {
  Activity,
  DollarSign,
  Zap,
  CheckCircle,
  XCircle,
  Loader2,
  RotateCw,
  Clock,
  Minus,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useAgentAnalytics } from "@/hooks/use-agents"
import { cn } from "@/lib/utils"
import { formatCurrency, formatCompactNumber } from "@/lib/format"
import { StatusRing } from "./status-ring"
import { ActivityFeed } from "./activity-feed"
import type { AgentDefinition, AgentInstance } from "@/types/agents"

interface OperationsDashboardProps {
  agent?: AgentDefinition
  onSelectRun?: (instance: AgentInstance) => void
}

const PERIOD_OPTIONS = [
  { value: "7", label: "7 days" },
  { value: "14", label: "14 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
]

export function OperationsDashboard({ agent, onSelectRun }: OperationsDashboardProps) {
  const [period, setPeriod] = React.useState("7")
  const days = Number(period)

  const {
    data: analytics,
    isLoading,
    isError,
    refetch,
  } = useAgentAnalytics(days, agent?.id)

  // Previous period for trend comparison (e.g. 7d current vs 14d to derive prev 7d)
  const { data: prevAnalytics } = useAgentAnalytics(days * 2, agent?.id)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-sm text-muted-foreground mb-2">Failed to load analytics</p>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RotateCw className="h-3.5 w-3.5 mr-1.5" />
          Retry
        </Button>
      </div>
    )
  }

  const totalRuns = analytics?.total_runs ?? 0
  const totalTokens = analytics?.total_tokens ?? 0
  const totalCost = analytics?.total_cost_usd ?? 0
  const avgSteps = analytics?.avg_steps_per_run ?? 0
  const statusBreakdown = analytics?.status_breakdown ?? {}

  const completedRuns = statusBreakdown.completed ?? 0
  const failedRuns = statusBreakdown.failed ?? 0
  const successRate = totalRuns > 0 ? (completedRuns / totalRuns) * 100 : 0

  // Success rate icon: check for good, X for bad, dash for no data
  const successIcon =
    totalRuns === 0
      ? Minus
      : successRate >= 90
        ? CheckCircle
        : successRate >= 50
          ? Activity
          : XCircle

  const successAccent =
    totalRuns === 0
      ? "text-muted-foreground"
      : successRate >= 90
        ? "text-emerald-500"
        : successRate >= 70
          ? "text-amber-500"
          : "text-red-500"

  // Derive previous-period values: (2x period total) - (current period) = previous period
  const prevRuns = (prevAnalytics?.total_runs ?? 0) - totalRuns
  const prevTokens = (prevAnalytics?.total_tokens ?? 0) - totalTokens
  const prevCost = (prevAnalytics?.total_cost_usd ?? 0) - totalCost

  function trendPct(current: number, previous: number): number | undefined {
    if (previous <= 0 || !prevAnalytics) return undefined
    return Math.round(((current - previous) / previous) * 100)
  }

  return (
    <div className="space-y-6">
      {/* Period selector */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold">Operations</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {agent ? agent.name : "All agents"} — last {days} days
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger className="w-28 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PERIOD_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => refetch()}
            aria-label="Refresh analytics"
          >
            <RotateCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MetricCard
          label="Total Runs"
          value={formatCompactNumber(totalRuns)}
          icon={Activity}
          accent="text-blue-500"
          trend={trendPct(totalRuns, prevRuns)}
        />
        <MetricCard
          label="Success Rate"
          value={totalRuns > 0 ? `${successRate.toFixed(0)}%` : "--"}
          icon={successIcon}
          accent={successAccent}
        />
        <MetricCard
          label="Tokens Used"
          value={formatCompactNumber(totalTokens)}
          icon={Zap}
          accent="text-violet-500"
          trend={trendPct(totalTokens, prevTokens)}
        />
        <MetricCard
          label="Total Cost"
          value={totalCost < 0.01 && totalCost > 0 ? `$${totalCost.toFixed(4)}` : formatCurrency(totalCost)}
          icon={DollarSign}
          accent="text-emerald-500"
          trend={trendPct(totalCost, prevCost)}
        />
      </div>

      {/* Status breakdown + Activity feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Status ring */}
        <Card className="lg:col-span-1">
          <CardContent className="p-5">
            <p className="text-xs font-medium text-muted-foreground mb-4">
              Status Breakdown
            </p>
            <StatusRing
              data={statusBreakdown}
              total={totalRuns}
            />
            {/* Legend */}
            <div className="mt-4 space-y-1.5">
              <StatusLegend label="Completed" count={completedRuns} color="bg-emerald-500" />
              <StatusLegend label="Failed" count={failedRuns} color="bg-red-500" />
              <StatusLegend label="Running" count={statusBreakdown.running ?? 0} color="bg-blue-500" />
              <StatusLegend label="Pending" count={statusBreakdown.pending ?? 0} color="bg-slate-400" />
            </div>
          </CardContent>
        </Card>

        {/* Activity feed — wired to drill-down */}
        <Card className="lg:col-span-2">
          <CardContent className="p-5">
            <p className="text-xs font-medium text-muted-foreground mb-4">
              Recent Activity
            </p>
            <ActivityFeed agentId={agent?.id} onSelectRun={onSelectRun} />
          </CardContent>
        </Card>
      </div>

      {/* Quick insights */}
      {totalRuns > 0 && (
        <div className="grid grid-cols-3 gap-3">
          <InsightCard
            label="Avg Steps / Run"
            value={avgSteps.toFixed(1)}
            icon={Clock}
          />
          <InsightCard
            label="Avg Cost / Run"
            value={
              (analytics?.avg_cost_per_run ?? 0) < 0.01
                ? `$${(analytics?.avg_cost_per_run ?? 0).toFixed(4)}`
                : formatCurrency(analytics?.avg_cost_per_run ?? 0)
            }
            icon={DollarSign}
          />
          <InsightCard
            label="Failure Rate"
            value={`${((failedRuns / totalRuns) * 100).toFixed(1)}%`}
            icon={XCircle}
          />
        </div>
      )}
    </div>
  )
}

// ── Sub-components ──

function MetricCard({
  label,
  value,
  icon: Icon,
  accent,
  trend,
}: {
  label: string
  value: string
  icon: React.ElementType
  accent: string
  trend?: number
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
          <Icon className={cn("h-3.5 w-3.5", accent)} />
        </div>
        <p className="text-2xl font-semibold tracking-tight">{value}</p>
        {trend !== undefined && (
          <p className={cn(
            "text-[11px] mt-1 font-medium",
            trend > 0 && "text-emerald-500",
            trend < 0 && "text-red-500",
            trend === 0 && "text-muted-foreground",
          )}>
            {trend > 0 ? "+" : ""}{trend}% vs prev period
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function InsightCard({
  label,
  value,
  icon: Icon,
}: {
  label: string
  value: string
  icon: React.ElementType
}) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="flex items-center gap-2 mb-1">
        <Icon className="h-3 w-3 text-muted-foreground" />
        <span className="text-[11px] text-muted-foreground">{label}</span>
      </div>
      <p className="text-sm font-semibold">{value}</p>
    </div>
  )
}

function StatusLegend({
  label,
  count,
  color,
}: {
  label: string
  count: number
  color: string
}) {
  return (
    <div className="flex items-center justify-between text-xs">
      <div className="flex items-center gap-2">
        <span className={cn("h-2 w-2 rounded-full", color)} />
        <span className="text-muted-foreground">{label}</span>
      </div>
      <span className="font-medium tabular-nums">{count}</span>
    </div>
  )
}
