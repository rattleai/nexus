import * as React from "react"
import { useNavigate, useParams } from "@tanstack/react-router"
import {
  Plus,
  Search,
  Loader2,
  CheckCircle2,
  XCircle,
  Square,
  Pause,
  Clock,
  MoreHorizontal,
  Pin,
  Copy,
  ShieldAlert,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  useAllInstances,
  useAgentDefinitions,
  usePendingApprovals,
  useStopInstance,
} from "@/hooks/use-agents"
import { useAgentStore } from "@/stores/agent-store"
import { formatRelativeTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import { NewRunDialog } from "./new-run-dialog"
import type { AgentInstance, AgentDefinition, InstanceStatus } from "@/types/agents"

// ── Status indicators ───────────────────────────────────────────

const statusIndicator: Record<InstanceStatus, { icon: React.ElementType; className: string; pulse?: boolean }> = {
  running: { icon: Loader2, className: "text-blue-500", pulse: true },
  pending: { icon: Clock, className: "text-yellow-500" },
  completed: { icon: CheckCircle2, className: "text-emerald-500" },
  failed: { icon: XCircle, className: "text-red-500" },
  cancelled: { icon: Square, className: "text-muted-foreground" },
  paused: { icon: Pause, className: "text-amber-500" },
}

// ── Date grouping ───────────────────────────────────────────────

function groupByDate(instances: AgentInstance[]): { label: string; items: AgentInstance[] }[] {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today.getTime() - 86_400_000)
  const weekAgo = new Date(today.getTime() - 7 * 86_400_000)

  const groups: Record<string, AgentInstance[]> = {
    Today: [],
    Yesterday: [],
    "This Week": [],
    Older: [],
  }

  for (const inst of instances) {
    const date = new Date(inst.created_at)
    if (date >= today) groups.Today.push(inst)
    else if (date >= yesterday) groups.Yesterday.push(inst)
    else if (date >= weekAgo) groups["This Week"].push(inst)
    else groups.Older.push(inst)
  }

  return Object.entries(groups)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }))
}

// ── Sidebar item ────────────────────────────────────────────────

function SessionItem({
  instance,
  agentDef,
  isActive,
  approvalCount,
  onSelect,
  onStop,
  onPin,
  isPinned,
}: {
  instance: AgentInstance
  agentDef: AgentDefinition | undefined
  isActive: boolean
  approvalCount: number
  onSelect: () => void
  onStop: () => void
  onPin: () => void
  isPinned: boolean
}) {
  const status = statusIndicator[instance.status]
  const StatusIcon = status.icon
  const isRunning = instance.status === "running"

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => e.key === "Enter" && onSelect()}
      className={cn(
        "group flex items-start gap-2.5 rounded-lg px-3 py-2.5 text-sm cursor-pointer transition-colors",
        isActive
          ? "bg-accent text-accent-foreground"
          : "hover:bg-muted/50",
      )}
    >
      {/* Status indicator */}
      <div className="mt-0.5 shrink-0">
        <StatusIcon
          className={cn(
            "h-4 w-4",
            status.className,
            isRunning && "animate-spin",
          )}
        />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 space-y-0.5">
        <div className="flex items-center gap-1.5">
          <span className="font-medium truncate">
            {agentDef?.name ?? "Unknown Agent"}
          </span>
          {approvalCount > 0 && (
            <Badge variant="outline" className="h-4 px-1 text-[10px] bg-amber-500/15 text-amber-600 border-amber-500/25 shrink-0">
              <ShieldAlert className="h-2.5 w-2.5 mr-0.5" />
              {approvalCount}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="font-mono">{instance.id.slice(0, 8)}</span>
          <span>·</span>
          <span>{formatRelativeTime(instance.created_at)}</span>
        </div>
      </div>

      {/* Actions dropdown */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
            onClick={(e) => e.stopPropagation()}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-36">
          <DropdownMenuItem
            onClick={(e) => {
              e.stopPropagation()
              onPin()
            }}
          >
            <Pin className="mr-2 h-3.5 w-3.5" />
            {isPinned ? "Unpin" : "Pin"}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={(e) => {
              e.stopPropagation()
              navigator.clipboard.writeText(instance.id)
            }}
          >
            <Copy className="mr-2 h-3.5 w-3.5" />
            Copy ID
          </DropdownMenuItem>
          {(instance.status === "running" || instance.status === "pending") && (
            <DropdownMenuItem
              onClick={(e) => {
                e.stopPropagation()
                onStop()
              }}
              className="text-destructive focus:text-destructive"
            >
              <Square className="mr-2 h-3.5 w-3.5" />
              Stop
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

// ── Main sidebar ────────────────────────────────────────────────

export function SessionSidebar() {
  const navigate = useNavigate()
  const params = useParams({ strict: false }) as { instanceId?: string }
  const activeInstanceId = params.instanceId ?? null

  const [search, setSearch] = React.useState("")
  const [statusFilter, setStatusFilter] = React.useState("all")
  const [newRunOpen, setNewRunOpen] = React.useState(false)

  const { data: instancesData, isLoading } = useAllInstances(
    statusFilter !== "all" ? statusFilter : undefined,
    1,
    100,
  )
  const { data: definitionsData } = useAgentDefinitions()
  const { data: approvalsData } = usePendingApprovals()
  const stopInstance = useStopInstance()
  const { pinnedInstanceIds, pinInstance, unpinInstance } = useAgentStore()

  // Build lookup maps
  const agentNameMap = React.useMemo(() => {
    const map = new Map<string, AgentDefinition>()
    for (const def of definitionsData?.items ?? []) {
      map.set(def.id, def)
    }
    return map
  }, [definitionsData])

  const approvalsByInstance = React.useMemo(() => {
    const map = new Map<string, number>()
    for (const a of approvalsData?.approvals ?? []) {
      const instId = (a as Record<string, unknown>).instance_id as string
      map.set(instId, (map.get(instId) ?? 0) + 1)
    }
    return map
  }, [approvalsData])

  const instances = instancesData?.items ?? []

  // Filter by search
  const filtered = React.useMemo(() => {
    if (!search.trim()) return instances
    const q = search.toLowerCase()
    return instances.filter((inst) => {
      const agentName = agentNameMap.get(inst.definition_id)?.name?.toLowerCase() ?? ""
      return inst.id.toLowerCase().includes(q) || agentName.includes(q)
    })
  }, [instances, search, agentNameMap])

  // Separate pinned and group rest by date
  const pinned = React.useMemo(
    () => filtered.filter((i) => pinnedInstanceIds.includes(i.id)),
    [filtered, pinnedInstanceIds],
  )
  const unpinned = React.useMemo(
    () => filtered.filter((i) => !pinnedInstanceIds.includes(i.id)),
    [filtered, pinnedInstanceIds],
  )
  const dateGroups = React.useMemo(() => groupByDate(unpinned), [unpinned])

  const handleSelect = (instanceId: string) => {
    navigate({ to: "/agents/$instanceId", params: { instanceId } })
  }

  const handleNewRunCreated = (instanceId: string) => {
    navigate({ to: "/agents/$instanceId", params: { instanceId } })
  }

  const totalApprovals = approvalsData?.approvals?.length ?? 0

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Header */}
      <div className="flex flex-col gap-2 p-3 border-b">
        <div className="flex items-center gap-2">
          <Button
            onClick={() => setNewRunOpen(true)}
            className="flex-1 gap-2"
            size="sm"
          >
            <Plus className="h-3.5 w-3.5" />
            New Run
          </Button>
          {totalApprovals > 0 && (
            <Badge variant="outline" className="bg-amber-500/15 text-amber-600 border-amber-500/25 shrink-0">
              <ShieldAlert className="h-3 w-3 mr-1" />
              {totalApprovals}
            </Badge>
          )}
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sessions..."
            className="h-8 pl-8 text-sm"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="running">Running</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
            <SelectItem value="paused">Paused</SelectItem>
            <SelectItem value="cancelled">Cancelled</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Session list */}
      <ScrollArea className="flex-1">
        <div className="p-2">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}

          {!isLoading && filtered.length === 0 && (
            <div className="text-center py-12 px-3">
              <p className="text-sm text-muted-foreground">
                {search ? "No sessions match your search." : "No sessions yet."}
              </p>
            </div>
          )}

          {/* Pinned section */}
          {pinned.length > 0 && (
            <div className="mb-2">
              <div className="flex items-center gap-1.5 px-3 py-1.5">
                <Pin className="h-3 w-3 text-muted-foreground" />
                <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                  Pinned
                </span>
              </div>
              {pinned.map((instance) => (
                <SessionItem
                  key={instance.id}
                  instance={instance}
                  agentDef={agentNameMap.get(instance.definition_id)}
                  isActive={instance.id === activeInstanceId}
                  approvalCount={approvalsByInstance.get(instance.id) ?? 0}
                  onSelect={() => handleSelect(instance.id)}
                  onStop={() => stopInstance.mutate(instance.id)}
                  onPin={() => unpinInstance(instance.id)}
                  isPinned
                />
              ))}
            </div>
          )}

          {/* Date-grouped sections */}
          {dateGroups.map((group) => (
            <div key={group.label} className="mb-2">
              <div className="px-3 py-1.5">
                <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
                  {group.label}
                </span>
              </div>
              {group.items.map((instance) => (
                <SessionItem
                  key={instance.id}
                  instance={instance}
                  agentDef={agentNameMap.get(instance.definition_id)}
                  isActive={instance.id === activeInstanceId}
                  approvalCount={approvalsByInstance.get(instance.id) ?? 0}
                  onSelect={() => handleSelect(instance.id)}
                  onStop={() => stopInstance.mutate(instance.id)}
                  onPin={() =>
                    pinnedInstanceIds.includes(instance.id)
                      ? unpinInstance(instance.id)
                      : pinInstance(instance.id)
                  }
                  isPinned={pinnedInstanceIds.includes(instance.id)}
                />
              ))}
            </div>
          ))}
        </div>
      </ScrollArea>

      {/* New Run Dialog */}
      <NewRunDialog
        open={newRunOpen}
        onOpenChange={setNewRunOpen}
        onCreated={handleNewRunCreated}
      />
    </div>
  )
}
