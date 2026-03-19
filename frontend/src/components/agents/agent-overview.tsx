import {
  Bot,
  Cpu,
  Clock,
  Zap,
  Shield,
  Activity,
  ArrowUpRight,
  Pencil,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { StatusDot, statusToVariant } from "@/components/status-dot"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { useAgentAnalytics, useAgentInstances } from "@/hooks/use-agents"
import { useAgentStore } from "@/stores/agent-store"
import type { AgentDefinition } from "@/types/agents"
import { cn } from "@/lib/utils"

interface AgentOverviewProps {
  agent: AgentDefinition
}

export function AgentOverview({ agent }: AgentOverviewProps) {
  const { setActiveTab } = useAgentStore()
  const { data: analytics, isError: analyticsError, refetch: refetchAnalytics } = useAgentAnalytics(7, agent.id)
  const { data: instances } = useAgentInstances(agent.id)

  const recentRuns = instances?.items?.slice(0, 5) ?? []
  const governancePolicy = agent.governance_policy ?? {}
  const hasGovernance =
    governancePolicy.max_spend_per_run_usd ||
    governancePolicy.max_spend_per_day_usd ||
    (governancePolicy.denied_tools && (governancePolicy.denied_tools as string[]).length > 0)

  return (
    <div className="space-y-6">
      {/* Hero card */}
      <div className="rounded-xl border bg-gradient-to-br from-background to-muted/30 p-6">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div
              className={cn(
                "flex h-14 w-14 items-center justify-center rounded-xl",
                agent.status === "active"
                  ? "bg-primary/10 text-primary"
                  : "bg-muted text-muted-foreground",
              )}
            >
              <Bot className="h-7 w-7" />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h2 className="text-xl font-semibold">{agent.name}</h2>
                <StatusDot variant={statusToVariant(agent.status)} />
                <span className="text-xs text-muted-foreground">v{agent.version}</span>
              </div>
              {agent.description && (
                <p className="text-sm text-muted-foreground mt-1 max-w-lg">
                  {agent.description}
                </p>
              )}
              <div className="flex items-center gap-4 mt-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <Cpu className="h-3.5 w-3.5" />
                  {agent.model}
                </span>
                {agent.temperature != null && (
                  <span>Temp: {agent.temperature}</span>
                )}
                <span className="flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5" />
                  Max {agent.max_duration_seconds}s
                </span>
                <span>Max {agent.max_steps_per_run} steps</span>
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setActiveTab("config")}
            >
              <Pencil className="mr-1.5 h-3.5 w-3.5" />
              Configure
            </Button>
            <Button size="sm" onClick={() => setActiveTab("chat")}>
              <Zap className="mr-1.5 h-3.5 w-3.5" />
              Run Agent
            </Button>
          </div>
        </div>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-4 gap-4">
        {analyticsError && (
          <div className="col-span-4 text-center py-2">
            <span className="text-xs text-muted-foreground">Failed to load analytics. </span>
            <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => refetchAnalytics()}>
              Retry
            </Button>
          </div>
        )}
        <Card>
          <CardContent className="p-4">
            <div className="text-2xl font-bold">{analytics?.total_runs ?? 0}</div>
            <div className="text-xs text-muted-foreground mt-1">Runs (7d)</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-2xl font-bold">
              {analytics?.total_tokens
                ? (analytics.total_tokens / 1000).toFixed(1) + "k"
                : "0"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Tokens (7d)</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-2xl font-bold">
              ${analytics?.total_cost_usd?.toFixed(2) ?? "0.00"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Cost (7d)</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="text-2xl font-bold">
              {analytics?.avg_steps_per_run?.toFixed(1) ?? "0"}
            </div>
            <div className="text-xs text-muted-foreground mt-1">Avg Steps</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Capabilities */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" />
              Capabilities
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Parallel Tools</span>
              <Badge variant={agent.parallel_tool_execution ? "default" : "secondary"}>
                {agent.parallel_tool_execution ? "Enabled" : "Disabled"}
              </Badge>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Sandbox</span>
              <Badge variant={agent.sandbox_enabled ? "default" : "secondary"}>
                {agent.sandbox_enabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Memory</span>
              <Badge
                variant={
                  agent.memory_config?.enabled ? "default" : "secondary"
                }
              >
                {agent.memory_config?.enabled ? "Enabled" : "Disabled"}
              </Badge>
            </div>
            {agent.allowed_tools.length > 0 && (
              <>
                <Separator />
                <div>
                  <div className="text-xs text-muted-foreground mb-2">
                    Tools ({agent.allowed_tools.length})
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {agent.allowed_tools.map((tool) => (
                      <Badge key={tool} variant="outline" className="text-xs">
                        {tool}
                      </Badge>
                    ))}
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Governance */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Shield className="h-4 w-4 text-primary" />
              Governance
              {!hasGovernance && (
                <Badge variant="outline" className="text-xs text-muted-foreground ml-auto">
                  Not configured
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {hasGovernance ? (
              <>
                {governancePolicy.max_spend_per_run_usd && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Per-run limit</span>
                    <span className="font-mono">
                      ${Number(governancePolicy.max_spend_per_run_usd).toFixed(2)}
                    </span>
                  </div>
                )}
                {governancePolicy.max_spend_per_day_usd && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Daily limit</span>
                    <span className="font-mono">
                      ${Number(governancePolicy.max_spend_per_day_usd).toFixed(2)}
                    </span>
                  </div>
                )}
                {governancePolicy.max_spend_per_month_usd && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Monthly limit</span>
                    <span className="font-mono">
                      ${Number(governancePolicy.max_spend_per_month_usd).toFixed(2)}
                    </span>
                  </div>
                )}
                {(governancePolicy.require_approval_for as string[] | undefined)?.length ? (
                  <div>
                    <div className="text-xs text-muted-foreground mb-1.5">
                      Requires approval
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {(governancePolicy.require_approval_for as string[]).map((t) => (
                        <Badge key={t} variant="outline" className="text-xs">
                          {t}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ) : null}
              </>
            ) : (
              <div className="text-sm text-muted-foreground">
                No spending limits or approval requirements configured.
                <Button
                  variant="link"
                  size="sm"
                  className="h-auto p-0 ml-1"
                  onClick={() => setActiveTab("governance")}
                >
                  Set up governance
                  <ArrowUpRight className="ml-0.5 h-3 w-3" />
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent runs */}
      {recentRuns.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" />
              Recent Runs
              <Button
                variant="link"
                size="sm"
                className="ml-auto h-auto p-0 text-xs"
                onClick={() => setActiveTab("runs")}
              >
                View all
                <ArrowUpRight className="ml-0.5 h-3 w-3" />
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {recentRuns.map((run) => (
                <div
                  key={run.id}
                  className="flex items-center gap-3 rounded-md border p-2.5 text-sm"
                >
                  <div
                    className={cn(
                      "h-2 w-2 rounded-full shrink-0",
                      run.status === "completed"
                        ? "bg-emerald-500"
                        : run.status === "running"
                          ? "bg-blue-500 animate-pulse"
                          : run.status === "failed"
                            ? "bg-red-500"
                            : "bg-muted-foreground",
                    )}
                  />
                  <span className="font-mono text-xs text-muted-foreground truncate">
                    {run.id.slice(0, 8)}
                  </span>
                  <Badge variant="outline" className="text-xs">
                    {run.status}
                  </Badge>
                  <span className="text-xs text-muted-foreground ml-auto">
                    {run.steps_executed} steps
                  </span>
                  <span className="text-xs text-muted-foreground">
                    ${run.cost_usd.toFixed(4)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {new Date(run.created_at).toLocaleTimeString()}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
