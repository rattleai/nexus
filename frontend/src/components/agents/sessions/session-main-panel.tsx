import * as React from "react"
import { useNavigate } from "@tanstack/react-router"
import {
  Square,
  Clock,
  Coins,
  Zap,
  Footprints,
  Bot,
  Loader2,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  Radio,
  ArrowLeft,
} from "lucide-react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  useInstanceDetail,
  useAgentDefinition,
  useStopInstance,
} from "@/hooks/use-agents"
import { useIsMobile } from "@/hooks/use-mobile"
import { cn } from "@/lib/utils"
import { formatDuration } from "@/lib/format"
import { statusConfig } from "./status-config"
import { StreamView } from "./stream-view"
import { AgentChatView } from "@/components/agents/chat"
import { getSessionId } from "@/lib/agent-stream-registry"

// ── Helpers ──────────────────────────────────────────────────────

function formatTimestamp(ts: string | null): string {
  if (!ts) return "--"
  return new Date(ts).toLocaleString()
}

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
          <pre className="overflow-x-auto max-w-full text-xs leading-relaxed max-h-48">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

// ── Main panel ──────────────────────────────────────────────────

interface SessionMainPanelProps {
  instanceId: string
}

export function SessionMainPanel({ instanceId }: SessionMainPanelProps) {
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const { data: instance, isLoading, error } = useInstanceDetail(instanceId)
  const { data: agentDef } = useAgentDefinition(instance?.definition_id ?? null)
  const stopInstance = useStopInstance()

  const isActive = instance?.status === "running" || instance?.status === "pending"
  const cfg = instance ? statusConfig[instance.status] : null

  const stepsProgress = instance && agentDef
    ? Math.min(100, (instance.steps_executed / agentDef.max_steps_per_run) * 100)
    : 0

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <AlertCircle className="h-8 w-8 text-red-500 mb-2" />
        <p className="text-sm font-medium text-red-500">Failed to load session</p>
        <p className="text-xs text-muted-foreground mt-1">Instance may have been deleted or is not accessible.</p>
      </div>
    )
  }

  if (!instance) return null

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 sm:px-6 pt-4 sm:pt-5 pb-3 sm:pb-4 border-b space-y-3">
        <div className="flex items-center gap-3">
          {/* Mobile back button */}
          {isMobile && (
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0 -ml-1"
              onClick={() => navigate({ to: "/agents" })}
            >
              <ArrowLeft className="h-4 w-4" />
            </Button>
          )}

          {/* Agent info */}
          <div className="flex items-center gap-2.5 flex-1 min-w-0">
            <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", cfg?.bg)}>
              <Bot className={cn("h-4 w-4", cfg?.color)} />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold truncate">
                {agentDef?.name ?? "Agent Instance"}
              </p>
              <p className="text-xs font-mono text-muted-foreground flex items-center gap-1">
                {instanceId.slice(0, 12)}...
                <CopyButton text={instanceId} />
              </p>
            </div>
          </div>

          {/* Status badge */}
          {cfg && (
            <Badge
              variant="outline"
              className={cn("capitalize text-xs shrink-0", cfg.bg, cfg.color)}
            >
              {isActive && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
              {instance.status}
            </Badge>
          )}
        </div>

        {/* Actions bar */}
        <div className="flex items-center gap-3">
          {isActive && (
            <Button
              variant="destructive"
              size="sm"
              className="h-8 text-xs"
              onClick={() => stopInstance.mutate(instanceId)}
              disabled={stopInstance.isPending}
            >
              <Square className="mr-1 h-3 w-3" />
              {stopInstance.isPending ? "Stopping..." : "Stop"}
            </Button>
          )}

          {/* Steps progress */}
          {agentDef && (
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

          {/* Inline metrics */}
          <div className="hidden sm:flex items-center gap-3 text-xs text-muted-foreground shrink-0">
            <span className="flex items-center gap-1">
              <Zap className="h-3 w-3" />
              {instance.tokens_used.toLocaleString()}
            </span>
            <span className="flex items-center gap-1">
              <Coins className="h-3 w-3" />
              ${instance.cost_usd.toFixed(4)}
            </span>
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {formatDuration(instance.started_at, instance.completed_at)}
            </span>
          </div>
        </div>
      </div>

      {/* Tabbed content */}
      <Tabs defaultValue="chat" className="flex flex-col flex-1 min-h-0">
        <div className="px-4 sm:px-6 pt-2">
          <TabsList>
            <TabsTrigger value="chat" className="text-xs gap-1.5">
              <Radio className="h-3 w-3" />
              Chat
            </TabsTrigger>
            <TabsTrigger value="stream" className="text-xs gap-1.5">
              Stream
            </TabsTrigger>
            <TabsTrigger value="details" className="text-xs">
              Details
            </TabsTrigger>
            <TabsTrigger value="metrics" className="text-xs">
              Metrics
            </TabsTrigger>
          </TabsList>
        </div>

        {/* Chat tab — interactive conversation */}
        <TabsContent value="chat" className="flex-1 min-h-0 mt-0">
          <AgentChatView
            instanceId={instanceId}
            sessionId={instance.session_id ?? getSessionId(instanceId)}
          />
        </TabsContent>

        {/* Stream tab — raw event log */}
        <TabsContent value="stream" className="flex-1 min-h-0 mt-0">
          <StreamView instanceId={instanceId} isActive={isActive} />
        </TabsContent>

        {/* Details tab */}
        <TabsContent value="details" className="flex-1 min-h-0 mt-0">
          <ScrollArea className="h-full">
            <div className="p-4 sm:p-6 space-y-4">
              {/* Instance ID */}
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs font-medium text-muted-foreground shrink-0">ID</span>
                <code className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono truncate min-w-0">
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

              {/* Data viewers */}
              <JsonViewer data={instance.input_data} label="Input Data" />
              <JsonViewer data={instance.output_data} label="Output Data" />
              <JsonViewer data={instance.last_checkpoint} label="Last Checkpoint" />

              {instance.error && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
                  <span className="text-xs font-semibold text-red-500 uppercase tracking-wider">
                    Error
                  </span>
                  <p className="text-sm text-red-600 dark:text-red-400 mt-1 whitespace-pre-wrap break-words">
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
            <div className="p-4 sm:p-6 space-y-4">
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
    </div>
  )
}
