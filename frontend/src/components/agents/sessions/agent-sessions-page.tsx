import * as React from "react"
import { Link } from "@tanstack/react-router"
import {
  Activity,
  Bot,
  Clock,
  Coins,
  Footprints,
  Loader2,
  RefreshCw,
  Search,
  Square,
  Zap,
  CheckCircle2,
  XCircle,
  Pause,
  AlertTriangle,
  ArrowLeft,
  ShieldAlert,
} from "lucide-react"
import { type ColumnDef } from "@tanstack/react-table"
import { PageHeader } from "@/components/page-header"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  useAllInstances,
  useAgentDefinitions,
  useStopInstance,
  usePendingApprovals,
} from "@/hooks/use-agents"
import { SessionsDataTable } from "./sessions-data-table"
import { SessionDetailPanel } from "./session-detail-panel"
import { ApprovalsBanner } from "./approvals-banner"
import { cn } from "@/lib/utils"
import type { AgentInstance, AgentDefinition, InstanceStatus } from "@/types/agents"

// ── Status config ────────────────────────────────────────────────

const STATUS_TABS: { value: string; label: string; icon: React.ElementType }[] = [
  { value: "all", label: "All", icon: Activity },
  { value: "running", label: "Running", icon: Loader2 },
  { value: "pending", label: "Pending", icon: Clock },
  { value: "completed", label: "Completed", icon: CheckCircle2 },
  { value: "failed", label: "Failed", icon: XCircle },
  { value: "cancelled", label: "Cancelled", icon: Square },
  { value: "paused", label: "Paused", icon: Pause },
]

const statusBadgeConfig: Record<
  InstanceStatus,
  { variant: "default" | "secondary" | "destructive" | "outline"; className: string }
> = {
  running: { variant: "default", className: "bg-blue-500/15 text-blue-700 dark:text-blue-400 border-blue-500/25" },
  pending: { variant: "outline", className: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-400 border-yellow-500/25" },
  completed: { variant: "secondary", className: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/25" },
  failed: { variant: "destructive", className: "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/25" },
  cancelled: { variant: "outline", className: "text-muted-foreground" },
  paused: { variant: "outline", className: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-amber-500/25" },
}

// ── Helpers ──────────────────────────────────────────────────────

function formatDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt) return "--"
  const start = new Date(startedAt).getTime()
  const end = completedAt ? new Date(completedAt).getTime() : Date.now()
  const ms = end - start
  if (ms < 1000) return `${ms}ms`
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds}s`
}

function formatRelativeTime(dateStr: string): string {
  const now = Date.now()
  const date = new Date(dateStr).getTime()
  const diff = now - date
  if (diff < 60_000) return "just now"
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return new Date(dateStr).toLocaleDateString()
}

// ── Stat card ────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  trend,
  className,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  trend?: "up" | "down" | "neutral"
  className?: string
}) {
  return (
    <Card className={cn("relative overflow-hidden", className)}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">{label}</p>
            <p className="text-2xl font-bold tracking-tight">{value}</p>
          </div>
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
            <Icon className="h-5 w-5 text-primary" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Main page ────────────────────────────────────────────────────

export function AgentSessionsPage() {
  const [statusFilter, setStatusFilter] = React.useState("all")
  const [searchQuery, setSearchQuery] = React.useState("")
  const [selectedRows, setSelectedRows] = React.useState<Set<string>>(new Set())
  const [selectedInstanceId, setSelectedInstanceId] = React.useState<string | null>(null)
  const [page, setPage] = React.useState(1)

  const { data: instancesData, isLoading, refetch } = useAllInstances(
    statusFilter !== "all" ? statusFilter : undefined,
    page,
  )
  const { data: definitionsData } = useAgentDefinitions()
  const { data: approvalsData } = usePendingApprovals()
  const stopInstance = useStopInstance()

  // Build agent name lookup map
  const agentNameMap = React.useMemo(() => {
    const map = new Map<string, AgentDefinition>()
    if (definitionsData?.items) {
      for (const def of definitionsData.items) {
        map.set(def.id, def)
      }
    }
    return map
  }, [definitionsData])

  const instances = instancesData?.items ?? []
  const totalPages = instancesData?.pages ?? 1

  // Filter by search query (agent name or instance ID)
  const filteredInstances = React.useMemo(() => {
    if (!searchQuery.trim()) return instances
    const q = searchQuery.toLowerCase()
    return instances.filter((inst) => {
      const agentName = agentNameMap.get(inst.definition_id)?.name?.toLowerCase() ?? ""
      return (
        inst.id.toLowerCase().includes(q) ||
        agentName.includes(q) ||
        inst.status.includes(q)
      )
    })
  }, [instances, searchQuery, agentNameMap])

  // Compute stats
  const stats = React.useMemo(() => {
    const all = instances
    return {
      running: all.filter((i) => i.status === "running").length,
      pending: all.filter((i) => i.status === "pending").length,
      completed: all.filter((i) => i.status === "completed").length,
      failed: all.filter((i) => i.status === "failed").length,
      totalCost: all.reduce((sum, i) => sum + (i.cost_usd ?? 0), 0),
      totalTokens: all.reduce((sum, i) => sum + (i.tokens_used ?? 0), 0),
    }
  }, [instances])

  const pendingApprovals = approvalsData?.approvals ?? []

  // Bulk actions
  const handleBulkStop = () => {
    for (const id of selectedRows) {
      const inst = instances.find((i) => i.id === id)
      if (inst && (inst.status === "running" || inst.status === "pending")) {
        stopInstance.mutate(id)
      }
    }
    setSelectedRows(new Set())
  }

  const toggleRow = (id: string) => {
    setSelectedRows((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAllRows = () => {
    if (selectedRows.size === filteredInstances.length) {
      setSelectedRows(new Set())
    } else {
      setSelectedRows(new Set(filteredInstances.map((i) => i.id)))
    }
  }

  // Columns definition
  const columns: ColumnDef<AgentInstance, unknown>[] = React.useMemo(
    () => [
      {
        id: "select",
        header: () => (
          <Checkbox
            checked={selectedRows.size === filteredInstances.length && filteredInstances.length > 0}
            onCheckedChange={toggleAllRows}
            aria-label="Select all"
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={selectedRows.has(row.original.id)}
            onCheckedChange={() => toggleRow(row.original.id)}
            aria-label={`Select instance ${row.original.id.slice(0, 8)}`}
          />
        ),
        enableSorting: false,
        size: 40,
      },
      {
        accessorKey: "definition_id",
        header: "Agent",
        cell: ({ row }) => {
          const def = agentNameMap.get(row.original.definition_id)
          return (
            <div className="flex items-center gap-2 min-w-0">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/10">
                <Bot className="h-3.5 w-3.5 text-primary" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium truncate">
                  {def?.name ?? "Unknown Agent"}
                </p>
                <p className="text-xs text-muted-foreground font-mono">
                  {row.original.id.slice(0, 8)}
                </p>
              </div>
            </div>
          )
        },
        size: 200,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => {
          const status = row.original.status
          const cfg = statusBadgeConfig[status]
          return (
            <Badge variant={cfg.variant} className={cn("capitalize text-xs", cfg.className)}>
              {status === "running" && (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              )}
              {status}
            </Badge>
          )
        },
        size: 120,
      },
      {
        accessorKey: "steps_executed",
        header: "Steps",
        cell: ({ row }) => (
          <div className="flex items-center gap-1.5 text-sm">
            <Footprints className="h-3.5 w-3.5 text-muted-foreground" />
            <span>{row.original.steps_executed}</span>
          </div>
        ),
        size: 80,
      },
      {
        accessorKey: "tokens_used",
        header: "Tokens",
        cell: ({ row }) => (
          <div className="flex items-center gap-1.5 text-sm">
            <Zap className="h-3.5 w-3.5 text-muted-foreground" />
            <span>{(row.original.tokens_used ?? 0).toLocaleString()}</span>
          </div>
        ),
        size: 100,
      },
      {
        accessorKey: "cost_usd",
        header: "Cost",
        cell: ({ row }) => (
          <div className="flex items-center gap-1.5 text-sm">
            <Coins className="h-3.5 w-3.5 text-muted-foreground" />
            <span>${(row.original.cost_usd ?? 0).toFixed(4)}</span>
          </div>
        ),
        size: 100,
      },
      {
        id: "duration",
        header: "Duration",
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {formatDuration(row.original.started_at, row.original.completed_at)}
          </span>
        ),
        size: 90,
      },
      {
        accessorKey: "created_at",
        header: "Started",
        cell: ({ row }) => (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-sm text-muted-foreground cursor-default">
                {formatRelativeTime(row.original.created_at)}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              {new Date(row.original.created_at).toLocaleString()}
            </TooltipContent>
          </Tooltip>
        ),
        size: 100,
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => {
          const inst = row.original
          const isActive = inst.status === "running" || inst.status === "pending"
          return (
            <div className="flex items-center gap-1 justify-end">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedInstanceId(inst.id)
                }}
              >
                Details
              </Button>
              {isActive && (
                <Button
                  variant="destructive"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={(e) => {
                    e.stopPropagation()
                    stopInstance.mutate(inst.id)
                  }}
                  disabled={stopInstance.isPending}
                >
                  <Square className="mr-1 h-3 w-3" />
                  Stop
                </Button>
              )}
            </div>
          )
        },
        size: 150,
      },
    ],
    [agentNameMap, selectedRows, filteredInstances.length, stopInstance],
  )

  return (
    <div className="flex flex-col flex-1 min-h-0 gap-6">
      {/* Header */}
      <PageHeader
        title="Agent Sessions"
        description="Monitor and manage all agent instances across your workspace"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link to="/agents">
                <ArrowLeft className="mr-1.5 h-3.5 w-3.5" />
                Agent Workspace
              </Link>
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isLoading}
            >
              <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", isLoading && "animate-spin")} />
              Refresh
            </Button>
          </div>
        }
      />

      {/* Approvals banner */}
      {pendingApprovals.length > 0 && (
        <ApprovalsBanner approvals={pendingApprovals} />
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatCard icon={Activity} label="Running" value={stats.running} />
        <StatCard icon={Clock} label="Pending" value={stats.pending} />
        <StatCard icon={CheckCircle2} label="Completed" value={stats.completed} />
        <StatCard icon={XCircle} label="Failed" value={stats.failed} />
        <StatCard icon={Zap} label="Total Tokens" value={stats.totalTokens.toLocaleString()} />
        <StatCard icon={Coins} label="Total Cost" value={`$${stats.totalCost.toFixed(4)}`} />
      </div>

      {/* Filters bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
        <Tabs
          value={statusFilter}
          onValueChange={(v) => {
            setStatusFilter(v)
            setPage(1)
          }}
        >
          <TabsList>
            {STATUS_TABS.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value} className="gap-1.5 text-xs">
                <tab.icon className={cn("h-3.5 w-3.5", tab.value === "running" && statusFilter === "running" && "animate-spin")} />
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="flex items-center gap-2 ml-auto">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search agents or IDs..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-8 w-[200px] pl-8 text-sm"
            />
          </div>
        </div>
      </div>

      {/* Bulk actions */}
      {selectedRows.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border bg-muted/50 px-4 py-2">
          <span className="text-sm font-medium">
            {selectedRows.size} selected
          </span>
          <Button
            variant="destructive"
            size="sm"
            className="h-7 text-xs"
            onClick={handleBulkStop}
          >
            <Square className="mr-1 h-3 w-3" />
            Stop Selected
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={() => setSelectedRows(new Set())}
          >
            Clear Selection
          </Button>
        </div>
      )}

      {/* Data table */}
      <div className="flex-1 min-h-0">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : filteredInstances.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-20 text-center">
              <Activity className="h-12 w-12 text-muted-foreground/30 mb-4" />
              <h3 className="text-lg font-semibold">No sessions found</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-md">
                {statusFilter !== "all"
                  ? `No ${statusFilter} sessions. Try a different status filter.`
                  : "No agent sessions yet. Run an agent from the Agent Workspace to see sessions here."}
              </p>
              <Button variant="outline" size="sm" className="mt-4" asChild>
                <Link to="/agents">Go to Agent Workspace</Link>
              </Button>
            </CardContent>
          </Card>
        ) : (
          <SessionsDataTable
            columns={columns}
            data={filteredInstances}
            onRowClick={(instance) => setSelectedInstanceId(instance.id)}
            selectedInstanceId={selectedInstanceId}
            page={page}
            totalPages={totalPages}
            onPageChange={setPage}
          />
        )}
      </div>

      {/* Detail panel */}
      {selectedInstanceId && (
        <SessionDetailPanel
          instanceId={selectedInstanceId}
          agentNameMap={agentNameMap}
          onClose={() => setSelectedInstanceId(null)}
        />
      )}
    </div>
  )
}
