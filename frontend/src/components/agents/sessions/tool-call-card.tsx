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

export interface ToolCallEntry {
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

export function ToolCallCard({ entry }: { entry: ToolCallEntry }) {
  const [expanded, setExpanded] = React.useState(false)

  return (
    <div className="rounded-lg border bg-card text-sm overflow-hidden">
      <button
        className="flex w-full items-center gap-2.5 px-3 py-3 text-left hover:bg-muted/30 transition-colors sm:py-2.5"
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
          <div className="px-3 py-2 border-b bg-muted/20">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Input
              </span>
            </div>
            <pre className="overflow-x-auto max-w-full rounded bg-muted p-2 text-xs max-h-32">
              {JSON.stringify(entry.args, null, 2)}
            </pre>
          </div>

          {entry.result != null && (
            <div className="px-3 py-2 bg-emerald-500/[0.03]">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                Output
              </span>
              <pre className="mt-1 overflow-x-auto max-w-full rounded bg-muted p-2 text-xs max-h-32">
                {typeof entry.result === "string"
                  ? entry.result
                  : JSON.stringify(entry.result, null, 2)}
              </pre>
            </div>
          )}

          {entry.error && (
            <div className="px-3 py-2 bg-red-500/[0.03]">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-red-500">
                Error
              </span>
              <pre className="mt-1 overflow-x-auto max-w-full rounded bg-red-500/10 p-2 text-xs text-red-600 dark:text-red-400 max-h-32">
                {entry.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
