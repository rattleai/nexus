import * as React from "react"
import {
  Loader2,
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { AgentToolCall } from "@/stores/agent-conversation-store"

interface AgentToolCallCardProps {
  toolCall: AgentToolCall
  className?: string
}

export function AgentToolCallCard({ toolCall, className }: AgentToolCallCardProps) {
  const [expanded, setExpanded] = React.useState(false)

  const StatusIcon = {
    pending: () => <Loader2 className="h-3.5 w-3.5 text-amber-500 animate-spin" />,
    running: () => <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin" />,
    completed: () => <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />,
    error: () => <AlertCircle className="h-3.5 w-3.5 text-red-500" />,
  }[toolCall.status]

  return (
    <div className={cn("rounded-lg border bg-card text-sm overflow-hidden", className)}>
      <button
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left hover:bg-muted/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md",
            toolCall.status === "pending" && "bg-amber-500/15",
            toolCall.status === "running" && "bg-blue-500/15",
            toolCall.status === "completed" && "bg-emerald-500/15",
            toolCall.status === "error" && "bg-red-500/15",
          )}
        >
          <StatusIcon />
        </div>
        <div className="flex-1 min-w-0">
          <span className="font-medium truncate block">{toolCall.toolName}</span>
        </div>
        {toolCall.durationMs != null && (
          <span className="text-xs text-muted-foreground shrink-0">
            {toolCall.durationMs < 1000
              ? `${toolCall.durationMs}ms`
              : `${(toolCall.durationMs / 1000).toFixed(1)}s`}
          </span>
        )}
        <Badge
          variant="outline"
          className={cn(
            "text-[10px] capitalize shrink-0",
            toolCall.status === "pending" && "text-amber-600 border-amber-500/30",
            toolCall.status === "running" && "text-blue-600 border-blue-500/30",
            toolCall.status === "completed" && "text-emerald-600 border-emerald-500/30",
            toolCall.status === "error" && "text-red-600 border-red-500/30",
          )}
        >
          {toolCall.status}
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
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Input
            </span>
            <pre className="mt-1 overflow-x-auto max-w-full rounded bg-muted p-2 text-xs max-h-32">
              {JSON.stringify(toolCall.args, null, 2)}
            </pre>
          </div>

          {/* Result */}
          {toolCall.result != null && (
            <div className="px-3 py-2 bg-emerald-500/[0.03]">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                Output
              </span>
              <pre className="mt-1 overflow-x-auto max-w-full rounded bg-muted p-2 text-xs max-h-32">
                {typeof toolCall.result === "string"
                  ? toolCall.result
                  : JSON.stringify(toolCall.result, null, 2)}
              </pre>
            </div>
          )}

          {/* Error */}
          {toolCall.error && (
            <div className="px-3 py-2 bg-red-500/[0.03]">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-red-500">
                Error
              </span>
              <pre className="mt-1 overflow-x-auto max-w-full rounded bg-red-500/10 p-2 text-xs text-red-600 dark:text-red-400 max-h-32">
                {toolCall.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
