import * as React from "react"
import {
  Square,
  Clock,
  Coins,
  Zap,
  Footprints,
  AlertCircle,
  CheckCircle,
  Loader2,
  Bot,
  ChevronDown,
  ChevronRight,
  Wrench,
  Copy,
  Check,
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
import { useAgentStore } from "@/stores/agent-store"
import { useInstanceDetail, useStopInstance } from "@/hooks/use-agents"
import { useInstanceStream } from "@/hooks/use-instance-stream"
import { cn } from "@/lib/utils"
import type { AgentStreamEvent, InstanceStatus } from "@/types/agents"

// ── Status badge config ──────────────────────────────────────────

const statusConfig: Record<
  InstanceStatus,
  { color: string; variant: "default" | "secondary" | "destructive" | "outline" }
> = {
  pending: { color: "text-yellow-500", variant: "outline" },
  running: { color: "text-blue-500", variant: "default" },
  paused: { color: "text-yellow-500", variant: "secondary" },
  completed: { color: "text-green-500", variant: "secondary" },
  failed: { color: "text-red-500", variant: "destructive" },
  cancelled: { color: "text-muted-foreground", variant: "outline" },
}

// ── Stream entry types (same as stream-pane) ─────────────────────

interface ContentEntry {
  id: string
  type: "content"
  text: string
}

interface ToolCallEntry {
  id: string
  type: "tool_call"
  toolName: string
  args: Record<string, unknown>
  status: "running" | "completed" | "error"
  result?: unknown
  error?: string
}

type StreamEntry = ContentEntry | ToolCallEntry

// ── JSON viewer component ────────────────────────────────────────

function JsonViewer({ data, label }: { data: unknown; label: string }) {
  const [collapsed, setCollapsed] = React.useState(false)
  const isEmpty =
    data === null ||
    data === undefined ||
    (typeof data === "object" && Object.keys(data as object).length === 0)

  if (isEmpty) {
    return (
      <div className="rounded-lg border p-3">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <p className="text-xs text-muted-foreground mt-1 italic">No data</p>
      </div>
    )
  }

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
          <pre className="overflow-x-auto max-w-full text-xs leading-relaxed">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

// ── Stat card ────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  className,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  className?: string
}) {
  return (
    <div className={cn("rounded-lg border p-3 space-y-1", className)}>
      <div className="flex items-center gap-1.5 text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span className="text-xs">{label}</span>
      </div>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  )
}

// ── Drawer tool call display (simplified) ────────────────────────

function DrawerToolCallCard({ entry }: { entry: ToolCallEntry }) {
  const [expanded, setExpanded] = React.useState(false)

  return (
    <div className="rounded-lg border bg-muted/30 text-sm">
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={() => setExpanded(!expanded)}
      >
        <Wrench className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        <span className="font-medium flex-1 truncate">{entry.toolName}</span>
        {entry.status === "running" && (
          <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin shrink-0" />
        )}
        {entry.status === "completed" && (
          <CheckCircle className="h-3.5 w-3.5 text-green-500 shrink-0" />
        )}
        {entry.status === "error" && (
          <AlertCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
        )}
        {expanded ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground" />
        )}
      </button>
      {expanded && (
        <div className="border-t px-3 py-2 space-y-2">
          <div>
            <span className="text-xs font-medium text-muted-foreground">Arguments</span>
            <pre className="mt-1 overflow-x-auto max-w-full rounded bg-muted p-2 text-xs">
              {JSON.stringify(entry.args, null, 2)}
            </pre>
          </div>
          {entry.result != null && (
            <div>
              <span className="text-xs font-medium text-muted-foreground">Result</span>
              <pre className="mt-1 overflow-x-auto max-w-full rounded bg-muted p-2 text-xs">
                {typeof entry.result === "string"
                  ? entry.result
                  : JSON.stringify(entry.result, null, 2)}
              </pre>
            </div>
          )}
          {entry.error && (
            <div>
              <span className="text-xs font-medium text-red-500">Error</span>
              <pre className="mt-1 overflow-x-auto max-w-full rounded bg-red-500/10 p-2 text-xs text-red-500">
                {entry.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Copy button ──────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = React.useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleCopy}>
      {copied ? (
        <Check className="h-3 w-3 text-green-500" />
      ) : (
        <Copy className="h-3 w-3" />
      )}
    </Button>
  )
}

// ── Format helpers ───────────────────────────────────────────────

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

function formatTimestamp(ts: string | null): string {
  if (!ts) return "--"
  return new Date(ts).toLocaleString()
}

// ── Stream tab content ───────────────────────────────────────────

function StreamTabContent({ instanceId }: { instanceId: string }) {
  const bottomRef = React.useRef<HTMLDivElement>(null)
  const [entries, setEntries] = React.useState<StreamEntry[]>([])
  const toolCallMapRef = React.useRef<Map<string, string>>(new Map())

  const handleEvent = React.useCallback((event: AgentStreamEvent) => {
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
              { id: crypto.randomUUID(), type: "content", text: event.data.content! },
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
                  ? { ...e, status: "completed" as const, result: event.data.tool_result }
                  : e,
              ),
            )
          }
        }
        break
      }
    }
  }, [])

  const { isConnected } = useInstanceStream({
    instanceId,
    onEvent: handleEvent,
    enabled: true,
  })

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [entries])

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-2">
        {entries.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            {isConnected ? (
              <>
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  Connected. Waiting for output...
                </p>
              </>
            ) : (
              <>
                <Bot className="h-6 w-6 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">
                  Connecting to instance stream...
                </p>
              </>
            )}
          </div>
        )}

        {entries.map((entry) => {
          if (entry.type === "content") {
            return (
              <div
                key={entry.id}
                className="text-sm whitespace-pre-wrap leading-relaxed"
              >
                {entry.text}
              </div>
            )
          }
          if (entry.type === "tool_call") {
            return <DrawerToolCallCard key={entry.id} entry={entry} />
          }
          return null
        })}

        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  )
}

// ── Main drawer component ────────────────────────────────────────

export function InstanceDetailDrawer() {
  const drawerInstanceId = useAgentStore((s) => s.drawerInstanceId)
  const closeDrawer = useAgentStore((s) => s.closeDrawer)
  const stopInstance = useStopInstance()

  const { data: instance, isLoading, error } = useInstanceDetail(drawerInstanceId)

  const isOpen = !!drawerInstanceId

  const handleStop = () => {
    if (drawerInstanceId) {
      stopInstance.mutate(drawerInstanceId)
    }
  }

  const isRunning = instance?.status === "running" || instance?.status === "pending"
  const statusCfg = instance ? statusConfig[instance.status] : null

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && closeDrawer()}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-none sm:w-[40%] min-w-[400px] flex flex-col p-0"
      >
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b space-y-2">
          <SheetHeader>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <SheetTitle className="truncate text-base">
                  Instance {drawerInstanceId?.slice(0, 8)}...
                </SheetTitle>
                {statusCfg && (
                  <Badge variant={statusCfg.variant} className="shrink-0">
                    {instance?.status}
                  </Badge>
                )}
              </div>
              {isRunning && (
                <Button
                  variant="destructive"
                  size="sm"
                  className="h-7 text-xs shrink-0"
                  onClick={handleStop}
                  disabled={stopInstance.isPending}
                >
                  <Square className="mr-1 h-3 w-3" />
                  {stopInstance.isPending ? "Stopping..." : "Stop"}
                </Button>
              )}
            </div>
            <SheetDescription>
              {instance
                ? `Definition: ${instance.definition_id.slice(0, 8)}...`
                : "Loading instance details..."}
            </SheetDescription>
          </SheetHeader>
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
              <p className="text-xs text-muted-foreground mt-1">
                {error instanceof Error ? error.message : "Unknown error"}
              </p>
            </div>
          )}

          {instance && drawerInstanceId && (
            <Tabs defaultValue="stream" className="flex flex-col h-full">
              <div className="px-6 pt-2">
                <TabsList className="w-full">
                  <TabsTrigger value="stream" className="flex-1">
                    Stream
                  </TabsTrigger>
                  <TabsTrigger value="details" className="flex-1">
                    Details
                  </TabsTrigger>
                  <TabsTrigger value="metrics" className="flex-1">
                    Metrics
                  </TabsTrigger>
                </TabsList>
              </div>

              {/* Stream Tab */}
              <TabsContent value="stream" className="flex-1 min-h-0 mt-0">
                {isRunning ? (
                  <StreamTabContent instanceId={drawerInstanceId} />
                ) : (
                  <div className="flex flex-col items-center justify-center h-full p-6 text-center">
                    <CheckCircle className="h-8 w-8 text-green-500 mb-2" />
                    <p className="text-sm font-medium">Instance {instance.status}</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      This instance is no longer streaming. Check the Details tab for output.
                    </p>
                  </div>
                )}
              </TabsContent>

              {/* Details Tab */}
              <TabsContent value="details" className="flex-1 min-h-0 mt-0">
                <ScrollArea className="h-full">
                  <div className="p-6 space-y-4">
                    {/* Instance ID */}
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-muted-foreground">
                        Instance ID
                      </span>
                      <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">
                        {instance.id}
                      </code>
                      <CopyButton text={instance.id} />
                    </div>

                    {/* Timestamps */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-0.5">
                        <span className="text-xs text-muted-foreground">Created</span>
                        <p className="text-xs font-medium">
                          {formatTimestamp(instance.created_at)}
                        </p>
                      </div>
                      <div className="space-y-0.5">
                        <span className="text-xs text-muted-foreground">Started</span>
                        <p className="text-xs font-medium">
                          {formatTimestamp(instance.started_at)}
                        </p>
                      </div>
                      <div className="space-y-0.5">
                        <span className="text-xs text-muted-foreground">Completed</span>
                        <p className="text-xs font-medium">
                          {formatTimestamp(instance.completed_at)}
                        </p>
                      </div>
                      <div className="space-y-0.5">
                        <span className="text-xs text-muted-foreground">Last Heartbeat</span>
                        <p className="text-xs font-medium">
                          {formatTimestamp(instance.last_heartbeat_at)}
                        </p>
                      </div>
                    </div>

                    {/* Input data */}
                    <JsonViewer data={instance.input_data} label="Input Data" />

                    {/* Output data */}
                    <JsonViewer data={instance.output_data} label="Output Data" />

                    {/* Last checkpoint */}
                    <JsonViewer data={instance.last_checkpoint} label="Last Checkpoint" />

                    {/* Error */}
                    {instance.error && (
                      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
                        <span className="text-xs font-medium text-red-500">Error</span>
                        <p className="text-sm text-red-500 mt-1 whitespace-pre-wrap">
                          {instance.error}
                        </p>
                      </div>
                    )}
                  </div>
                </ScrollArea>
              </TabsContent>

              {/* Metrics Tab */}
              <TabsContent value="metrics" className="flex-1 min-h-0 mt-0">
                <ScrollArea className="h-full">
                  <div className="p-6 space-y-4">
                    <div className="grid grid-cols-2 gap-3">
                      <StatCard
                        icon={Zap}
                        label="Tokens Used"
                        value={instance.tokens_used.toLocaleString()}
                      />
                      <StatCard
                        icon={Coins}
                        label="Cost (USD)"
                        value={`$${instance.cost_usd.toFixed(4)}`}
                      />
                      <StatCard
                        icon={Footprints}
                        label="Steps Executed"
                        value={instance.steps_executed}
                      />
                      <StatCard
                        icon={Clock}
                        label="Duration"
                        value={formatDuration(instance.started_at, instance.completed_at)}
                      />
                    </div>

                    {/* Duration breakdown */}
                    <div className="rounded-lg border p-3 space-y-2">
                      <span className="text-xs font-medium">Duration Breakdown</span>
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-muted-foreground">Queue Time</span>
                          <span className="font-medium">
                            {instance.started_at && instance.created_at
                              ? formatDuration(instance.created_at, instance.started_at)
                              : "--"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-muted-foreground">Execution Time</span>
                          <span className="font-medium">
                            {formatDuration(instance.started_at, instance.completed_at)}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-muted-foreground">Total Time</span>
                          <span className="font-medium">
                            {formatDuration(instance.created_at, instance.completed_at)}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Per-step averages */}
                    {instance.steps_executed > 0 && (
                      <div className="rounded-lg border p-3 space-y-2">
                        <span className="text-xs font-medium">Per-Step Averages</span>
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-muted-foreground">Tokens / Step</span>
                            <span className="font-medium">
                              {Math.round(
                                instance.tokens_used / instance.steps_executed,
                              ).toLocaleString()}
                            </span>
                          </div>
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-muted-foreground">Cost / Step</span>
                            <span className="font-medium">
                              $
                              {(instance.cost_usd / instance.steps_executed).toFixed(
                                4,
                              )}
                            </span>
                          </div>
                        </div>
                      </div>
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
