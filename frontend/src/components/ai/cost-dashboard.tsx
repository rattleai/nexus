import * as React from "react"
import { useTranslation } from "react-i18next"
import { DollarSign, Hash, TrendingUp, Cpu } from "lucide-react"
import { cn } from "@/lib/utils"
import { formatCurrency, formatCompactNumber } from "@/lib/format"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import { StatCard } from "@/components/stat-card"

export interface CostData {
  model: string
  provider: string
  inputTokens: number
  outputTokens: number
  cost: number
  requests: number
  date: string
}

export interface CostDashboardProps {
  data: CostData[]
  budget?: number
  className?: string
}

interface ModelBreakdown {
  model: string
  provider: string
  totalCost: number
  totalRequests: number
  totalInputTokens: number
  totalOutputTokens: number
}

function aggregateByModel(data: CostData[]): ModelBreakdown[] {
  const map = new Map<string, ModelBreakdown>()

  for (const entry of data) {
    const existing = map.get(entry.model)
    if (existing) {
      existing.totalCost += entry.cost
      existing.totalRequests += entry.requests
      existing.totalInputTokens += entry.inputTokens
      existing.totalOutputTokens += entry.outputTokens
    } else {
      map.set(entry.model, {
        model: entry.model,
        provider: entry.provider,
        totalCost: entry.cost,
        totalRequests: entry.requests,
        totalInputTokens: entry.inputTokens,
        totalOutputTokens: entry.outputTokens,
      })
    }
  }

  return Array.from(map.values()).sort((a, b) => b.totalCost - a.totalCost)
}

export function CostDashboard({ data, budget, className }: CostDashboardProps) {
  const { t } = useTranslation("ai")
  const totalSpend = React.useMemo(
    () => data.reduce((sum, d) => sum + d.cost, 0),
    [data],
  )
  const totalRequests = React.useMemo(
    () => data.reduce((sum, d) => sum + d.requests, 0),
    [data],
  )
  const avgCostPerRequest = totalRequests > 0 ? totalSpend / totalRequests : 0
  const modelBreakdowns = React.useMemo(() => aggregateByModel(data), [data])
  const maxModelCost = modelBreakdowns[0]?.totalCost ?? 0
  const budgetUsage = budget && budget > 0 ? (totalSpend / budget) * 100 : null

  return (
    <div className={cn("space-y-6", className)}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title={t("cost_dashboard.total_spend")}
          value={formatCurrency(totalSpend)}
          icon={DollarSign}
        />
        <StatCard
          title={t("cost_dashboard.total_requests")}
          value={formatCompactNumber(totalRequests)}
          icon={Hash}
        />
        <StatCard
          title={t("cost_dashboard.avg_cost_per_request")}
          value={
            avgCostPerRequest < 0.01
              ? `$${avgCostPerRequest.toFixed(4)}`
              : formatCurrency(avgCostPerRequest)
          }
          icon={TrendingUp}
        />
        <StatCard
          title={t("cost_dashboard.models_used")}
          value={modelBreakdowns.length}
          icon={Cpu}
        />
      </div>

      {budgetUsage != null && budget != null && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">{t("cost_dashboard.budget_usage")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span
                className={cn(
                  budgetUsage >= 90
                    ? "text-destructive"
                    : budgetUsage >= 75
                      ? "text-amber-600 dark:text-amber-400"
                      : "text-muted-foreground",
                )}
              >
                {formatCurrency(totalSpend)} of {formatCurrency(budget)} (
                {budgetUsage.toFixed(1)}%)
              </span>
              <span className="text-muted-foreground">
                {formatCurrency(Math.max(0, budget - totalSpend))} remaining
              </span>
            </div>
            <Progress value={Math.min(budgetUsage, 100)} className="h-2" />
          </CardContent>
        </Card>
      )}

      {modelBreakdowns.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">
              {t("cost_dashboard.spend_by_model")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {modelBreakdowns.map((breakdown, index) => (
                <React.Fragment key={breakdown.model}>
                  {index > 0 && <Separator />}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-bold">
                          {breakdown.provider.charAt(0).toUpperCase()}
                        </span>
                        <span className="text-sm font-medium">
                          {breakdown.model}
                        </span>
                      </div>
                      <span className="text-sm font-medium">
                        {formatCurrency(breakdown.totalCost)}
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                      <div
                        className="h-full rounded-full bg-primary transition-all"
                        style={{
                          width: `${maxModelCost > 0 ? (breakdown.totalCost / maxModelCost) * 100 : 0}%`,
                        }}
                      />
                    </div>
                    <div className="flex gap-4 text-xs text-muted-foreground">
                      <span>
                        {formatCompactNumber(breakdown.totalRequests)} requests
                      </span>
                      <span>
                        {formatCompactNumber(
                          breakdown.totalInputTokens +
                            breakdown.totalOutputTokens,
                        )}{" "}
                        tokens
                      </span>
                    </div>
                  </div>
                </React.Fragment>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
