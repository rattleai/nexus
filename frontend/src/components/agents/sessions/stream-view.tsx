import * as React from "react"
import {
  Bot,
  Loader2,
  CheckCircle,
  AlertCircle,
  Radio,
} from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { usePendingApprovals } from "@/hooks/use-agents"
import { useInstanceStream } from "@/hooks/use-instance-stream"
import { cn } from "@/lib/utils"
import { ToolCallCard, type ToolCallEntry } from "./tool-call-card"
import { InlineApproval } from "./inline-approval"
import type { AgentStreamEvent } from "@/types/agents"

// ── Stream entry types ──────────────────────────────────

export interface ContentEntry {
  id: string
  type: "content"
  text: string
  timestamp: number
}

export interface StepEntry {
  id: string
  type: "step"
  step: number
  tokens?: number
  cost?: number
  timestamp: number
}

export interface StatusEntry {
  id: string
  type: "status"
  status: string
  message?: string
  timestamp: number
}

export type StreamEntry = ContentEntry | ToolCallEntry | StepEntry | StatusEntry

// ── StreamView component ────────────────────────────────

interface StreamViewProps {
  instanceId: string
  isActive: boolean
}

export function StreamView({ instanceId, isActive }: StreamViewProps) {
  const bottomRef = React.useRef<HTMLDivElement>(null)
  const [entries, setEntries] = React.useState<StreamEntry[]>([])
  const toolCallMapRef = React.useRef<Map<string, string>>(new Map())
  const { data: approvalsData } = usePendingApprovals()

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
                  No stream data available. Check the Details tab for output.
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
                  className="text-sm whitespace-pre-wrap break-words leading-relaxed rounded-lg bg-muted/30 px-3 py-2"
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
