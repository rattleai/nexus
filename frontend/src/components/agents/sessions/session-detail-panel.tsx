import * as React from "react"
import {
  X,
  Square,
  Clock,
  Coins,
  Zap,
  Footprints,
  Bot,
  Loader2,
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Wrench,
  Copy,
  Check,
  ExternalLink,
  ShieldAlert,
  XCircle,
  Radio,
} from "lucide-react"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  useInstanceDetail,
  useStopInstance,
  usePendingApprovals,
  useResolveApproval,
} from "@/hooks/use-agents"
import { useInstanceStream } from "@/hooks/use-instance-stream"
import { cn } from "@/lib/utils"
import type { AgentDefinition, AgentStreamEvent, InstanceStatus } from "@/types/agents"

// ── Status config ────────────────────────────────────────────────

const statusConfig: Record<
  InstanceStatus,
  { color: string; bg: string; label: string }
> = {
  pending: { color: "text-yellow-600", bg: "bg-yellow-500/15", label: "Pending" },
  running: { color: "text-blue-600", bg: "bg-blue-500/15", label: "Running" },
  paused: { color: "text-amber-600", bg: "bg-amber-500/15", label: "Paused" },
  completed: { color: "text-emerald-600", bg: "bg-emerald-500/15", label: "Completed" },
  failed: { color: "text-red-600", bg: "bg-red-500/15", label: "Failed" },
  cancelled: { color: "text-muted-foreground", bg: "bg-muted", label: "Cancelled" },
}

// ── Stream types ─────────────────────────────────────────────────

interface ContentEntry {
  id: string
  type: "content"
  text: string
  timestamp: number
}

interface ToolCallEntry {
  id: string
  type: "tool_call"
  toolName: string
  args: Record<string, unknown>
  status: "running" | "completed" | "error"
  result?: unknown
  error?: string
  timestamp: number
  durationMs?: number
}

interface StepEntry {
  id: string
  type: "step"
  step: number
  tokens?: number
  cost?: number
  timestamp: number
}

interface StatusEntry {
  id: string
  type: "status"
  status: string
  message?: string
  timestamp: number
}

type StreamEntry = ContentEntry | ToolCallEntry | StepEntry | StatusEntry

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
  return `${minutes}m ${seconds % 60}s`
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return "--"
  return new Date(ts).toLocaleString()
}

// ── Copy button ──────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = React.useState(false)

  return (
    <Button
      variant="ghost"
      size="icon"
      className="h-6 w-6"
      onClick={async () => {
        await navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
    >
      {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
    </Button>
  )
}

// ── JSON viewer ──────────────────────────────────────────────────

function JsonViewer({ data, label }: { data: unknown; label: string }) {
  const [collapsed, setCollapsed] = React.useState(true)
  const isEmpty =
    data === null ||
    data === undefined ||
    (typeof data === "object" && Object.keys(data as object).length === 0)

  if (isEmpty) return null

  return (
    <div className="rounded-lg border">
      <button
        className="flex items-center gap-1.5 w-full px-3 py-2 text-left hover:bg-muted/50"
        onClick={() => setCollapsed(!collapsed)}
      >
        {collapsed ? (
          <ChevronRight className="h-3 w-3 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        )}
        <span className="text-xs font-medium">{label}</span>
      </button>
      {!collapsed && (
        <div className="border-t px-3 py-2">
          <pre className="overflow-x-auto text-xs leading-relaxed max-h-48">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

// ── Tool call card (enhanced with shadcn/ai style) ───────────────

function ToolCallCard({ entry }: { entry: ToolCallEntry }) {
  const [expanded, setExpanded] = React.useState(false)

  return (
    <div className="rounded-lg border bg-card text-sm overflow-hidden">
      <button
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left hover:bg-muted/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
            entry.status === "running" && "bg-blue-500/15",
            entry.status === "completed" && "bg-emerald-500/15",
            entry.status === "error" && "bg-red-500/15",
          )}
        >
          {entry.status === "running" ? (
            <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin" />
          ) : entry.status === "completed" ? (
            <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />
          ) : (
            <AlertCircle className="h-3.5 w-3.5 text-red-500" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <span className="font-medium truncate block">{entry.toolName}</span>
        </div>
        {entry.durationMs != null && (
          <span className="text-xs text-muted-foreground shrink-0">
            {entry.durationMs < 1000 ? `${entry.durationMs}ms` : `${(entry.durationMs / 1000).toFixed(1)}s`}
          </span>
        )}
        <Badge
          variant="outline"
          className={cn(
            "text-[10px] capitalize shrink-0",
            entry.status === "running" && "text-blue-600 border-blue-500/30",
            entry.status === "completed" && "text-emerald-600 border-emerald-500/30",
            entry.status === "error" && "text-red-600 border-red-500/30",
          )}
        >
          {entry.status}
        </Badge>
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />
        )}
      </button>

      {expanded && (
        <div className="border-t">
          {/* Arguments */}
          <div className="px-3 py-2 border-b bg-muted/20">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Input
              </span>
            </div>
            <pre className="overflow-x-auto rounded bg-muted p-2 text-xs max-h-32">
              {JSON.stringify(entry.args, null, 2)}
            </pre>
          </div>

          {/* Result */}
          {entry.result != null && (
            <div className="px-3 py-2 bg-emerald-500/[0.03]">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                Output
              </span>
              <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-xs max-h-32">
                {typeof entry.result === "string"
                  ? entry.result
                  : JSON.stringify(entry.result, null, 2)}
              </pre>
            </div>
          )}

          {/* Error */}
          {entry.error && (
            <div className="px-3 py-2 bg-red-500/[0.03]">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-red-500">
                Error
              </span>
              <pre className="mt-1 overflow-x-auto rounded bg-red-500/10 p-2 text-xs text-red-600 dark:text-red-400 max-h-32">
                {entry.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Approval action inline ───────────────────────────────────────

function InlineApproval({ approval }: { approval: Record<string, unknown> }) {
  const resolveApproval = useResolveApproval()
  const [resolved, setResolved] = React.useState<string | null>(null)

  const handleResolve = (decision: "approved" | "denied") => {
    resolveApproval.mutate(
      { approvalId: approval.approval_id as string, decision },
      { onSuccess: () => setResolved(decision) },
    )
  }

  if (resolved) {
    return (
      <div className="flex items-center gap-2 rounded-lg border px-3 py-2 bg-muted/30">
        {resolved === "approved" ? (
          <CheckCircle className="h-4 w-4 text-emerald-500" />
        ) : (
          <XCircle className="h-4 w-4 text-red-500" />
        )}
        <span className="text-sm capitalize">{resolved}</span>
        <span className="text-xs text-muted-foreground">
          {approval.tool_name as string}
        </span>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 overflow-hidden">
      <div className="flex items-center gap-3 px-3 py-2.5">
        <ShieldAlert className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">
            Approval needed: <code className="text-xs bg-muted px-1 rounded">{approval.tool_name as string}</code>
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            The agent wants to execute this tool and is waiting for your decision.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs border-red-500/30 text-red-600 hover:bg-red-500/10"
            onClick={() => handleResolve("denied")}
            disabled={resolveApproval.isPending}
          >
            Deny
          </Button>
          <Button
            size="sm"
            className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
            onClick={() => handleResolve("approved")}
            disabled={resolveApproval.isPending}
          >
            {resolveApproval.isPending ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <CheckCircle className="mr-1 h-3 w-3" />
            )}
            Approve
          </Button>
        </div>
      </div>
      {approval.arguments && Object.keys(approval.arguments as object).length > 0 && (
        <div className="border-t border-amber-500/20 px-3 py-2 bg-amber-500/[0.02]">
          <pre className="text-xs overflow-x-auto max-h-24">
            {JSON.stringify(approval.arguments, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

// ── Stream view ──────────────────────────────────────────────────

function StreamView({
  instanceId,
  isActive,
}: {
  instanceId: string
  isActive: boolean
}) {
  const bottomRef = React.useRef<HTMLDivElement>(null)
  const [entries, setEntries] = React.useState<StreamEntry[]>([])
  const toolCallMapRef = React.useRef<Map<string, string>>(new Map())
  const { data: approvalsData } = usePendingApprovals()

  // Filter approvals for this instance
  const instanceApprovals = React.useMemo(
    () =>
      (approvalsData?.approvals ?? []).filter(
        (a) => (a as Record<string, unknown>).instance_id === instanceId,
      ),
    [approvalsData, instanceId],
  )

  const handleEvent = React.useCallback((event: AgentStreamEvent) => {
    const now = Date.now()
    switch (event.event) {
      case "content_delta": {
        if (event.data.content) {
          setEntries((prev) => {
            const last = prev[prev.length - 1]
            if (last && last.type === "content") {
              return [
                ...prev.slice(0, -1),
                { ...last, text: last.text + event.data.content },
              ]
            }
            return [
              ...prev,
              { id: crypto.randomUUID(), type: "content", text: event.data.content!, timestamp: now },
            ]
          })
        }
        break
      }
      case "tool_call": {
        if (event.data.tool_name) {
          const entryId = crypto.randomUUID()
          toolCallMapRef.current.set(event.data.tool_name, entryId)
          setEntries((prev) => [
            ...prev,
            {
              id: entryId,
              type: "tool_call",
              toolName: event.data.tool_name!,
              args: event.data.tool_args ?? {},
              status: "running",
              timestamp: now,
            },
          ])
        }
        break
      }
      case "tool_result": {
        if (event.data.tool_name) {
          const entryId = toolCallMapRef.current.get(event.data.tool_name)
          if (entryId) {
            setEntries((prev) =>
              prev.map((e) =>
                e.id === entryId && e.type === "tool_call"
                  ? {
                      ...e,
                      status: "completed" as const,
                      result: event.data.tool_result,
                      durationMs: now - e.timestamp,
                    }
                  : e,
              ),
            )
          }
        }
        break
      }
      case "step_completed": {
        setEntries((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            type: "step",
            step: event.data.step ?? 0,
            tokens: event.data.tokens,
            cost: event.data.cost,
            timestamp: now,
          },
        ])
        break
      }
      case "instance_completed":
      case "instance_failed":
      case "run_completed": {
        setEntries((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            type: "status",
            status: event.event === "instance_failed" ? "failed" : "completed",
            message: event.data.error ?? event.data.message,
            timestamp: now,
          },
        ])
        break
      }
    }
  }, [])

  const { isConnected } = useInstanceStream({
    instanceId,
    onEvent: handleEvent,
    enabled: isActive,
  })

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [entries])

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-3">
        {/* Connection status */}
        {isActive && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground mb-2">
            <Radio
              className={cn(
                "h-3 w-3",
                isConnected ? "text-emerald-500" : "text-muted-foreground",
              )}
            />
            {isConnected ? "Connected to live stream" : "Connecting..."}
          </div>
        )}

        {/* Pending approvals for this instance */}
        {instanceApprovals.map((approval) => (
          <InlineApproval
            key={(approval as Record<string, unknown>).approval_id as string}
            approval={approval as Record<string, unknown>}
          />
        ))}

        {/* Stream entries */}
        {entries.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            {isActive ? (
              <>
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  {isConnected ? "Waiting for agent output..." : "Connecting to stream..."}
                </p>
              </>
            ) : (
              <>
                <Bot className="h-6 w-6 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  Instance is no longer active. Check the Details tab for output.
                </p>
              </>
            )}
          </div>
        )}

        {entries.map((entry) => {
          switch (entry.type) {
            case "content":
              return (
                <div
                  key={entry.id}
                  className="text-sm whitespace-pre-wrap leading-relaxed rounded-lg bg-muted/30 px-3 py-2"
                >
                  {entry.text}
                </div>
              )
            case "tool_call":
              return <ToolCallCard key={entry.id} entry={entry} />
            case "step":
              return (
                <div
                  key={entry.id}
                  className="flex items-center gap-2 text-xs text-muted-foreground py-1"
                >
                  <Separator className="flex-1" />
                  <span>
                    Step {entry.step}
                    {entry.tokens != null && ` · ${entry.tokens} tokens`}
                    {entry.cost != null && ` · $${entry.cost.toFixed(4)}`}
                  </span>
                  <Separator className="flex-1" />
                </div>
              )
            case "status":
              return (
                <div
                  key={entry.id}
                  className={cn(
                    "flex items-center gap-2 rounded-lg px-3 py-2 text-sm",
                    entry.status === "completed"
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : "bg-red-500/10 text-red-700 dark:text-red-400",
                  )}
                >
                  {entry.status === "completed" ? (
                    <CheckCircle className="h-4 w-4 shrink-0" />
                  ) : (
                    <AlertCircle className="h-4 w-4 shrink-0" />
                  )}
                  <span className="capitalize font-medium">{entry.status}</span>
                  {entry.message && (
                    <span className="text-xs opacity-80 truncate">— {entry.message}</span>
                  )}
                </div>
              )
            default:
              return null
          }
        })}

        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  )
}

// ── Main detail panel ────────────────────────────────────────────

interface SessionDetailPanelProps {
  instanceId: string
  agentNameMap: Map<string, AgentDefinition>
  onClose: () => void
}

export function SessionDetailPanel({
  instanceId,
  agentNameMap,
  onClose,
}: SessionDetailPanelProps) {
  const { data: instance, isLoading, error } = useInstanceDetail(instanceId)
  const stopInstance = useStopInstance()

  const agentDef = instance ? agentNameMap.get(instance.definition_id) : undefined
  const isActive = instance?.status === "running" || instance?.status === "pending"
  const cfg = instance ? statusConfig[instance.status] : null

  const stepsProgress = instance && agentDef
    ? Math.min(100, (instance.steps_executed / agentDef.max_steps_per_run) * 100)
    : 0

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-none sm:w-[480px] flex flex-col p-0"
      >
        {/* Header */}
        <div className="px-5 pt-5 pb-4 border-b space-y-3">
          <SheetHeader className="space-y-1">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", cfg?.bg)}>
                  <Bot className={cn("h-4 w-4", cfg?.color)} />
                </div>
                <div className="min-w-0">
                  <SheetTitle className="text-sm truncate">
                    {agentDef?.name ?? "Agent Instance"}
                  </SheetTitle>
                  <SheetDescription className="text-xs font-mono flex items-center gap-1">
                    {instanceId.slice(0, 12)}...
                    <CopyButton text={instanceId} />
                  </SheetDescription>
                </div>
              </div>
              {cfg && (
                <Badge
                  variant="outline"
                  className={cn("capitalize text-xs shrink-0", cfg.bg, cfg.color)}
                >
                  {isActive && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
                  {instance?.status}
                </Badge>
              )}
            </div>
          </SheetHeader>

          {/* Quick actions */}
          <div className="flex items-center gap-2">
            {isActive && (
              <Button
                variant="destructive"
                size="sm"
                className="h-7 text-xs"
                onClick={() => stopInstance.mutate(instanceId)}
                disabled={stopInstance.isPending}
              >
                <Square className="mr-1 h-3 w-3" />
                {stopInstance.isPending ? "Stopping..." : "Stop Instance"}
              </Button>
            )}
            {/* Steps progress */}
            {instance && agentDef && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex-1 flex items-center gap-2 min-w-0">
                    <Progress value={stepsProgress} className="h-1.5 flex-1" />
                    <span className="text-[10px] text-muted-foreground shrink-0">
                      {instance.steps_executed}/{agentDef.max_steps_per_run}
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  Step {instance.steps_executed} of {agentDef.max_steps_per_run} max
                </TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-hidden">
          {isLoading && (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {error && (
            <div className="flex flex-col items-center justify-center h-full p-6 text-center">
              <AlertCircle className="h-8 w-8 text-red-500 mb-2" />
              <p className="text-sm font-medium text-red-500">Failed to load instance</p>
            </div>
          )}

          {instance && (
            <Tabs defaultValue="stream" className="flex flex-col h-full">
              <div className="px-5 pt-2">
                <TabsList className="w-full">
                  <TabsTrigger value="stream" className="flex-1 text-xs">
                    <Radio className="mr-1.5 h-3 w-3" />
                    Live
                  </TabsTrigger>
                  <TabsTrigger value="details" className="flex-1 text-xs">
                    Details
                  </TabsTrigger>
                  <TabsTrigger value="metrics" className="flex-1 text-xs">
                    Metrics
                  </TabsTrigger>
                </TabsList>
              </div>

              {/* Stream / Live tab */}
              <TabsContent value="stream" className="flex-1 min-h-0 mt-0">
                <StreamView instanceId={instanceId} isActive={isActive} />
              </TabsContent>

              {/* Details tab */}
              <TabsContent value="details" className="flex-1 min-h-0 mt-0">
                <ScrollArea className="h-full">
                  <div className="p-5 space-y-4">
                    {/* Instance ID */}
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-muted-foreground">ID</span>
                      <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">
                        {instance.id}
                      </code>
                      <CopyButton text={instance.id} />
                    </div>

                    {/* Agent info */}
                    {agentDef && (
                      <Card>
                        <CardContent className="p-3">
                          <div className="flex items-center gap-2">
                            <Bot className="h-4 w-4 text-primary shrink-0" />
                            <div className="min-w-0">
                              <p className="text-sm font-medium">{agentDef.name}</p>
                              <p className="text-xs text-muted-foreground">
                                {agentDef.model} · {agentDef.description?.slice(0, 60) ?? "No description"}
                              </p>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    )}

                    {/* Timestamps */}
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        ["Created", instance.created_at],
                        ["Started", instance.started_at],
                        ["Completed", instance.completed_at],
                        ["Last Heartbeat", instance.last_heartbeat_at],
                      ].map(([label, ts]) => (
                        <div key={label} className="space-y-0.5">
                          <span className="text-xs text-muted-foreground">{label}</span>
                          <p className="text-xs font-medium">{formatTimestamp(ts)}</p>
                        </div>
                      ))}
                    </div>

                    {/* Input / Output / Error */}
                    <JsonViewer data={instance.input_data} label="Input Data" />
                    <JsonViewer data={instance.output_data} label="Output Data" />
                    <JsonViewer data={instance.last_checkpoint} label="Last Checkpoint" />

                    {instance.error && (
                      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
                        <span className="text-xs font-semibold text-red-500 uppercase tracking-wider">
                          Error
                        </span>
                        <p className="text-sm text-red-600 dark:text-red-400 mt-1 whitespace-pre-wrap">
                          {instance.error}
                        </p>
                      </div>
                    )}
                  </div>
                </ScrollArea>
              </TabsContent>

              {/* Metrics tab */}
              <TabsContent value="metrics" className="flex-1 min-h-0 mt-0">
                <ScrollArea className="h-full">
                  <div className="p-5 space-y-4">
                    {/* Stat grid */}
                    <div className="grid grid-cols-2 gap-3">
                      {[
                        { icon: Zap, label: "Tokens", value: instance.tokens_used.toLocaleString() },
                        { icon: Coins, label: "Cost", value: `$${instance.cost_usd.toFixed(4)}` },
                        { icon: Footprints, label: "Steps", value: instance.steps_executed },
                        {
                          icon: Clock,
                          label: "Duration",
                          value: formatDuration(instance.started_at, instance.completed_at),
                        },
                      ].map((s) => (
                        <Card key={s.label}>
                          <CardContent className="p-3 space-y-1">
                            <div className="flex items-center gap-1.5 text-muted-foreground">
                              <s.icon className="h-3.5 w-3.5" />
                              <span className="text-xs">{s.label}</span>
                            </div>
                            <p className="text-lg font-bold">{s.value}</p>
                          </CardContent>
                        </Card>
                      ))}
                    </div>

                    {/* Duration breakdown */}
                    <Card>
                      <CardContent className="p-3 space-y-2">
                        <span className="text-xs font-semibold">Duration Breakdown</span>
                        {[
                          {
                            label: "Queue Time",
                            value:
                              instance.started_at && instance.created_at
                                ? formatDuration(instance.created_at, instance.started_at)
                                : "--",
                          },
                          {
                            label: "Execution Time",
                            value: formatDuration(instance.started_at, instance.completed_at),
                          },
                          {
                            label: "Total Time",
                            value: formatDuration(instance.created_at, instance.completed_at),
                          },
                        ].map((d) => (
                          <div key={d.label} className="flex items-center justify-between text-xs">
                            <span className="text-muted-foreground">{d.label}</span>
                            <span className="font-medium">{d.value}</span>
                          </div>
                        ))}
                      </CardContent>
                    </Card>

                    {/* Per-step averages */}
                    {instance.steps_executed > 0 && (
                      <Card>
                        <CardContent className="p-3 space-y-2">
                          <span className="text-xs font-semibold">Per-Step Averages</span>
                          {[
                            {
                              label: "Tokens / Step",
                              value: Math.round(
                                instance.tokens_used / instance.steps_executed,
                              ).toLocaleString(),
                            },
                            {
                              label: "Cost / Step",
                              value: `$${(instance.cost_usd / instance.steps_executed).toFixed(4)}`,
                            },
                          ].map((d) => (
                            <div key={d.label} className="flex items-center justify-between text-xs">
                              <span className="text-muted-foreground">{d.label}</span>
                              <span className="font-medium">{d.value}</span>
                            </div>
                          ))}
                        </CardContent>
                      </Card>
                    )}
                  </div>
                </ScrollArea>
              </TabsContent>
            </Tabs>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
