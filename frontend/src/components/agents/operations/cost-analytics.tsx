import * as React from "react"
import {
  DollarSign,
  Zap,
  TrendingUp,
  BarChart3,
  Loader2,
  RotateCw,
} from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
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
import type { AgentDefinition, AgentAnalytics } from "@/types/agents"

interface CostAnalyticsProps {
  agent?: AgentDefinition
  budget?: number
}

const PERIODS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
]

export function CostAnalytics({ agent, budget }: CostAnalyticsProps) {
  const [period, setPeriod] = React.useState("30")
  const days = Number(period)

  const { data: analytics, isLoading, refetch } = useAgentAnalytics(days, agent?.id)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const totalCost = analytics?.total_cost_usd ?? 0
  const totalTokens = analytics?.total_tokens ?? 0
  const totalRuns = analytics?.total_runs ?? 0
  const avgCostPerRun = analytics?.avg_cost_per_run ?? 0
  const topAgents = analytics?.top_agents ?? []

  const budgetPct = budget && budget > 0 ? Math.min((totalCost / budget) * 100, 100) : null
  const budgetRemaining = budget ? Math.max(0, budget - totalCost) : null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold">Cost & Usage</h3>
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
              {PERIODS.map((p) => (
                <SelectItem key={p.value} value={p.value}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => refetch()}>
            <RotateCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <SummaryCard
          label="Total Spend"
          value={totalCost < 0.01 && totalCost > 0 ? `$${totalCost.toFixed(4)}` : formatCurrency(totalCost)}
          icon={DollarSign}
          accent="text-emerald-500"
        />
        <SummaryCard
          label="Total Tokens"
          value={formatCompactNumber(totalTokens)}
          icon={Zap}
          accent="text-violet-500"
        />
        <SummaryCard
          label="Avg / Run"
          value={avgCostPerRun < 0.01 ? `$${avgCostPerRun.toFixed(4)}` : formatCurrency(avgCostPerRun)}
          icon={TrendingUp}
          accent="text-blue-500"
        />
        <SummaryCard
          label="Total Runs"
          value={formatCompactNumber(totalRuns)}
          icon={BarChart3}
          accent="text-amber-500"
        />
      </div>

      {/* Budget tracker */}
      {budgetPct !== null && budget !== undefined && (
        <Card>
          <CardContent className="p-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-muted-foreground">Budget Usage</p>
              <p className="text-xs text-muted-foreground">
                {formatCurrency(budgetRemaining ?? 0)} remaining
              </p>
            </div>
            <Progress value={budgetPct} className="h-2" />
            <div className="flex items-center justify-between text-xs">
              <span
                className={cn(
                  "font-medium",
                  budgetPct >= 90
                    ? "text-red-500"
                    : budgetPct >= 75
                      ? "text-amber-500"
                      : "text-emerald-500",
                )}
              >
                {budgetPct.toFixed(1)}% used
              </span>
              <span className="text-muted-foreground">
                {formatCurrency(totalCost)} of {formatCurrency(budget)}
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Top agents by cost */}
      {topAgents.length > 0 && (
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-medium text-muted-foreground mb-4">
              Top Agents by Spend
            </p>
            <div className="space-y-3">
              {topAgents.map((agent, i) => {
                const maxCost = topAgents[0]?.total_cost_usd ?? 1
                const pct = (agent.total_cost_usd / maxCost) * 100
                return (
                  <div key={agent.agent_id} className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-muted text-[10px] font-bold">
                          {i + 1}
                        </span>
                        <span className="text-sm font-medium truncate">{agent.name}</span>
                      </div>
                      <span className="text-sm font-medium tabular-nums">
                        {formatCurrency(agent.total_cost_usd)}
                      </span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full bg-primary transition-all duration-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="flex gap-4 text-[11px] text-muted-foreground">
                      <span>{agent.runs} runs</span>
                      <span>{formatCompactNumber(agent.total_tokens)} tokens</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Token efficiency */}
      {totalRuns > 0 && (
        <div className="grid grid-cols-2 gap-3">
          <EfficiencyCard
            label="Tokens / Run"
            value={formatCompactNumber(totalTokens / totalRuns)}
            description="Average token consumption per execution"
          />
          <EfficiencyCard
            label="Cost / 1K Tokens"
            value={
              totalTokens > 0
                ? `$${((totalCost / totalTokens) * 1000).toFixed(4)}`
                : "--"
            }
            description="Effective rate across all models"
          />
        </div>
      )}
    </div>
  )
}

// ── Sub-components ──

function SummaryCard({
  label,
  value,
  icon: Icon,
  accent,
}: {
  label: string
  value: string
  icon: React.ElementType
  accent: string
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
      </CardContent>
    </Card>
  )
}

function EfficiencyCard({
  label,
  value,
  description,
}: {
  label: string
  value: string
  description: string
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mb-1">
          {label}
        </p>
        <p className="text-xl font-semibold tabular-nums">{value}</p>
        <p className="text-[11px] text-muted-foreground mt-1">{description}</p>
      </CardContent>
    </Card>
  )
}
