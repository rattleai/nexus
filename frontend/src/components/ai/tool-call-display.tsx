import { useState } from "react"
import {
  CheckCircle,
  XCircle,
  Loader2,
  Clock,
  ChevronDown,
  ChevronRight,
  Wrench,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown>
  status: "pending" | "running" | "completed" | "error"
  result?: unknown
  error?: string
  duration?: number
}

interface ToolCallDisplayProps {
  toolCall: ToolCall
  onApprove?: (id: string) => void
  onDeny?: (id: string) => void
  className?: string
}

const statusConfig: Record<
  ToolCall["status"],
  { icon: React.ElementType; color: string; label: string }
> = {
  pending: { icon: Clock, color: "text-yellow-500", label: "Pending" },
  running: { icon: Loader2, color: "text-blue-500", label: "Running" },
  completed: { icon: CheckCircle, color: "text-green-500", label: "Completed" },
  error: { icon: XCircle, color: "text-red-500", label: "Error" },
}

export function ToolCallDisplay({
  toolCall,
  onApprove,
  onDeny,
  className,
}: ToolCallDisplayProps) {
  const [argsOpen, setArgsOpen] = useState(false)
  const [resultOpen, setResultOpen] = useState(false)

  const config = statusConfig[toolCall.status]
  const StatusIcon = config.icon

  return (
    <div
      className={cn(
        "rounded-lg border bg-muted/30 text-sm",
        className,
      )}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <Wrench className="h-4 w-4 text-muted-foreground shrink-0" />
        <span className="font-medium flex-1 truncate">{toolCall.name}</span>
        <StatusIcon
          className={cn(
            "h-4 w-4 shrink-0",
            config.color,
            toolCall.status === "running" && "animate-spin",
          )}
        />
        <Badge variant="outline" className="text-xs">
          {config.label}
        </Badge>
        {toolCall.duration != null && (
          <span className="text-xs text-muted-foreground">
            {toolCall.duration}ms
          </span>
        )}
      </div>

      <div className="border-t px-3 py-1.5">
        <button
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => setArgsOpen(!argsOpen)}
        >
          {argsOpen ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
          Arguments
        </button>
        {argsOpen && (
          <pre className="mt-1 overflow-x-auto rounded bg-muted p-2 text-xs">
            {JSON.stringify(toolCall.arguments, null, 2)}
          </pre>
        )}
      </div>

      {(toolCall.result != null || toolCall.error) && (
        <div className="border-t px-3 py-1.5">
          <button
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setResultOpen(!resultOpen)}
          >
            {resultOpen ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            {toolCall.error ? "Error" : "Result"}
          </button>
          {resultOpen && (
            <pre
              className={cn(
                "mt-1 overflow-x-auto rounded p-2 text-xs",
                toolCall.error ? "bg-red-500/10 text-red-500" : "bg-muted",
              )}
            >
              {toolCall.error ?? JSON.stringify(toolCall.result, null, 2)}
            </pre>
          )}
        </div>
      )}

      {toolCall.status === "pending" && (onApprove || onDeny) && (
        <div className="flex gap-2 border-t px-3 py-2">
          {onApprove && (
            <Button
              size="sm"
              variant="default"
              className="h-7 text-xs"
              onClick={() => onApprove(toolCall.id)}
            >
              Approve
            </Button>
          )}
          {onDeny && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => onDeny(toolCall.id)}
            >
              Deny
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
