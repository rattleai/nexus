import * as React from "react"
import {
  X,
  Square,
  LockOpen,
  Lock,
  Bot,
  Clock,
  Coins,
  Footprints,
  Zap,
  ChevronDown,
  ChevronRight,
  Wrench,
  Loader2,
  CheckCircle,
  AlertCircle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useInstanceStream } from "@/hooks/use-instance-stream"
import { useAllActiveInstances, useStopInstance } from "@/hooks/use-agents"
import { useMultiStreamStore } from "@/stores/multi-stream-store"
import { useAgentStore } from "@/stores/agent-store"
import { cn } from "@/lib/utils"
import type { AgentStreamEvent } from "@/types/agents"

interface StreamPaneProps {
  instanceId: string | null
  agentName: string
  paneId: string
  isFocused: boolean
}

// ── Status indicator config ──────────────────────────────────────

type StreamState = "idle" | "thinking" | "acting" | "complete" | "error"

const stateConfig: Record<
  StreamState,
  { color: string; dotColor: string; label: string }
> = {
  idle: { color: "text-muted-foreground", dotColor: "bg-muted-foreground", label: "Idle" },
  thinking: { color: "text-purple-500", dotColor: "bg-purple-500", label: "Thinking" },
  acting: { color: "text-blue-500", dotColor: "bg-blue-500", label: "Acting" },
  complete: { color: "text-green-500", dotColor: "bg-green-500", label: "Complete" },
  error: { color: "text-red-500", dotColor: "bg-red-500", label: "Error" },
}

// ── Streamed content entry types ─────────────────────────────────

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

// ── Tool call card ───────────────────────────────────────────────

function ToolCallCard({ entry }: { entry: ToolCallEntry }) {
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
            <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-xs">
              {JSON.stringify(entry.args, null, 2)}
            </pre>
          </div>
          {entry.result != null && (
            <div>
              <span className="text-xs font-medium text-muted-foreground">Result</span>
              <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-xs">
                {typeof entry.result === "string"
                  ? entry.result
                  : JSON.stringify(entry.result, null, 2)}
              </pre>
            </div>
          )}
          {entry.error && (
            <div>
              <span className="text-xs font-medium text-red-500">Error</span>
              <pre className="mt-1 overflow-x-auto rounded bg-red-500/10 p-2 text-xs text-red-500">
                {entry.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Format elapsed time ──────────────────────────────────────────

function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  const seconds = Math.floor(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds}s`
}

// ── StreamPane component ─────────────────────────────────────────

export function StreamPane({ instanceId, agentName, paneId, isFocused }: StreamPaneProps) {
  const bottomRef = React.useRef<HTMLDivElement>(null)
  const startTimeRef = React.useRef<number | null>(null)
  const [elapsed, setElapsed] = React.useState(0)
  const [entries, setEntries] = React.useState<StreamEntry[]>([])

  const streamState = useMultiStreamStore((s) => s.streams[instanceId ?? ""])
  const {
    initStream,
    updateStreamState,
    completeStream,
    errorStream,
    toggleScrollLock,
  } = useMultiStreamStore()

  const { removeStreamPane, focusPane, assignInstanceToPane } = useAgentStore()
  const stopInstance = useStopInstance()
  const activeInstances = useAllActiveInstances({ enabled: !instanceId })

  const scrollLocked = streamState?.scrollLocked ?? false
  const agentState: StreamState = streamState?.agentState ?? "idle"
  const tokens = streamState?.tokens ?? 0
  const cost = streamState?.cost ?? 0
  const steps = streamState?.steps ?? 0
  const isStreaming = streamState?.isStreaming ?? false

  // Track tool calls by name for matching results
  const toolCallMapRef = React.useRef<Map<string, string>>(new Map())

  // Initialize stream state when instanceId is assigned
  React.useEffect(() => {
    if (instanceId) {
      initStream(instanceId, "", agentName)
      startTimeRef.current = Date.now()
      setEntries([])
      toolCallMapRef.current.clear()
    }
  }, [instanceId, agentName, initStream])

  // Elapsed timer
  React.useEffect(() => {
    if (!isStreaming || !startTimeRef.current) return
    const interval = setInterval(() => {
      setElapsed(Date.now() - (startTimeRef.current ?? Date.now()))
    }, 1000)
    return () => clearInterval(interval)
  }, [isStreaming])

  // Handle SSE events
  const handleEvent = React.useCallback(
    (event: AgentStreamEvent) => {
      if (!instanceId) return

      switch (event.event) {
        case "content_delta": {
          if (event.data.content) {
            setEntries((prev) => {
              const last = prev[prev.length - 1]
              if (last && last.type === "content") {
                // Append to existing content entry
                return [
                  ...prev.slice(0, -1),
                  { ...last, text: last.text + event.data.content },
                ]
              }
              // New content entry
              return [
                ...prev,
                { id: crypto.randomUUID(), type: "content", text: event.data.content! },
              ]
            })
            updateStreamState(instanceId, { agentState: "thinking" })
          }
          break
        }

        case "thinking": {
          updateStreamState(instanceId, { agentState: "thinking" })
          if (event.data.tokens) {
            updateStreamState(instanceId, {
              tokens: (streamState?.tokens ?? 0) + event.data.tokens,
            })
          }
          if (event.data.cost) {
            updateStreamState(instanceId, {
              cost: (streamState?.cost ?? 0) + event.data.cost,
            })
          }
          break
        }

        case "step_started": {
          if (event.data.step) {
            updateStreamState(instanceId, { steps: event.data.step })
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
            updateStreamState(instanceId, { agentState: "acting" })
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

        case "run_completed":
        case "instance_completed": {
          if (event.data.tokens) {
            updateStreamState(instanceId, { tokens: event.data.tokens })
          }
          if (event.data.cost) {
            updateStreamState(instanceId, { cost: event.data.cost })
          }
          completeStream(instanceId)
          break
        }

        case "instance_failed":
        case "error": {
          errorStream(instanceId, event.data.message ?? event.data.error ?? "Unknown error")
          break
        }
      }
    },
    [instanceId, streamState?.tokens, streamState?.cost, updateStreamState, completeStream, errorStream],
  )

  const handleDone = React.useCallback(() => {
    if (instanceId) completeStream(instanceId)
  }, [instanceId, completeStream])

  const handleError = React.useCallback(
    (err: Error) => {
      if (instanceId) errorStream(instanceId, err.message)
    },
    [instanceId, errorStream],
  )

  useInstanceStream({
    instanceId,
    onEvent: handleEvent,
    onDone: handleDone,
    onError: handleError,
    enabled: !!instanceId,
  })

  // Auto-scroll
  React.useEffect(() => {
    if (!scrollLocked) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [entries, scrollLocked])

  const config = stateConfig[agentState]

  const handleStop = () => {
    if (instanceId) {
      stopInstance.mutate(instanceId)
    }
  }

  const handleClose = () => {
    removeStreamPane(paneId)
  }

  const handleSelectInstance = (selectedInstanceId: string) => {
    const instance = activeInstances.data?.items.find((i) => i.id === selectedInstanceId)
    if (instance) {
      assignInstanceToPane(paneId, selectedInstanceId)
    }
  }

  // ── Empty state (no instance assigned) ───────────────────────

  if (!instanceId) {
    return (
      <div
        role="button"
        tabIndex={0}
        className={cn(
          "flex flex-col h-full rounded-lg border bg-card",
          isFocused && "ring-2 ring-primary/50",
        )}
        onClick={() => focusPane(paneId)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault()
            focusPane(paneId)
          }
        }}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b">
          <span className="text-sm font-medium text-muted-foreground">{agentName}</span>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={handleClose}>
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-muted text-muted-foreground mb-3">
            <Bot className="h-6 w-6" />
          </div>
          <p className="text-sm font-medium mb-1">Select an instance to stream</p>
          <p className="text-xs text-muted-foreground mb-4">
            Choose a running agent instance to observe its real-time output.
          </p>
          {activeInstances.data && activeInstances.data.items.length > 0 ? (
            <Select onValueChange={handleSelectInstance}>
              <SelectTrigger className="w-64">
                <SelectValue placeholder="Select a running instance..." />
              </SelectTrigger>
              <SelectContent>
                {activeInstances.data.items.map((inst) => (
                  <SelectItem key={inst.id} value={inst.id}>
                    <span className="truncate">
                      {inst.id.slice(0, 8)}... ({inst.status})
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <p className="text-xs text-muted-foreground">No running instances available.</p>
          )}
        </div>
      </div>
    )
  }

  // ── Active stream pane ─────────────────────────────────────────

  return (
    <div
      role="button"
      tabIndex={0}
      className={cn(
        "flex flex-col h-full rounded-lg border bg-card",
        isFocused && "ring-2 ring-primary/50",
      )}
      onClick={() => focusPane(paneId)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          focusPane(paneId)
        }
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium truncate">{agentName}</span>
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "h-2 w-2 rounded-full shrink-0",
                config.dotColor,
                isStreaming && "animate-pulse",
              )}
            />
            <span className={cn("text-xs", config.color)}>{config.label}</span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={(e) => {
              e.stopPropagation()
              if (instanceId) toggleScrollLock(instanceId)
            }}
            title={scrollLocked ? "Unlock scroll" : "Lock scroll"}
          >
            {scrollLocked ? (
              <Lock className="h-3.5 w-3.5" />
            ) : (
              <LockOpen className="h-3.5 w-3.5" />
            )}
          </Button>
          {isStreaming && (
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-red-500 hover:text-red-600"
              onClick={(e) => {
                e.stopPropagation()
                handleStop()
              }}
              title="Stop instance"
            >
              <Square className="h-3.5 w-3.5" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={(e) => {
              e.stopPropagation()
              handleClose()
            }}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Content */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="p-3 space-y-2">
          {entries.length === 0 && !isStreaming && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Bot className="h-8 w-8 text-muted-foreground mb-2" />
              <p className="text-sm text-muted-foreground">Waiting for stream data...</p>
            </div>
          )}

          {entries.length === 0 && isStreaming && (
            <div className="flex items-center gap-2 py-4 justify-center">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Connecting to stream...</span>
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
              return <ToolCallCard key={entry.id} entry={entry} />
            }
            return null
          })}

          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* Footer metrics */}
      <div className="flex items-center gap-3 px-3 py-1.5 border-t text-[11px] text-muted-foreground">
        <div className="flex items-center gap-1" title="Tokens used">
          <Zap className="h-3 w-3" />
          <span>{tokens.toLocaleString()}</span>
        </div>
        <div className="flex items-center gap-1" title="Cost">
          <Coins className="h-3 w-3" />
          <span>${cost.toFixed(4)}</span>
        </div>
        <div className="flex items-center gap-1" title="Steps executed">
          <Footprints className="h-3 w-3" />
          <span>{steps}</span>
        </div>
        <div className="flex items-center gap-1 ml-auto" title="Elapsed time">
          <Clock className="h-3 w-3" />
          <span>{formatElapsed(elapsed)}</span>
        </div>
      </div>
    </div>
  )
}
