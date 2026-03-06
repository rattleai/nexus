import {
  Brain,
  Zap,
  Clock,
  AlertCircle,
  CheckCircle,
  Circle,
} from "lucide-react"
import { cn } from "@/lib/utils"

export type AgentState = "idle" | "thinking" | "acting" | "waiting" | "error" | "complete"

export interface AgentStatusProps {
  state: AgentState
  message?: string
  className?: string
}

const stateConfig: Record<
  AgentState,
  { icon: React.ElementType; color: string; pulseColor: string; label: string }
> = {
  idle: {
    icon: Circle,
    color: "text-muted-foreground",
    pulseColor: "",
    label: "Idle",
  },
  thinking: {
    icon: Brain,
    color: "text-purple-500",
    pulseColor: "bg-purple-500/20",
    label: "Thinking",
  },
  acting: {
    icon: Zap,
    color: "text-blue-500",
    pulseColor: "bg-blue-500/20",
    label: "Acting",
  },
  waiting: {
    icon: Clock,
    color: "text-yellow-500",
    pulseColor: "bg-yellow-500/20",
    label: "Waiting",
  },
  error: {
    icon: AlertCircle,
    color: "text-red-500",
    pulseColor: "",
    label: "Error",
  },
  complete: {
    icon: CheckCircle,
    color: "text-green-500",
    pulseColor: "",
    label: "Complete",
  },
}

export function AgentStatus({ state, message, className }: AgentStatusProps) {
  const config = stateConfig[state]
  const Icon = config.icon
  const isActive = state === "thinking" || state === "acting" || state === "waiting"

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm",
        className,
      )}
    >
      <span className="relative flex h-5 w-5 items-center justify-center">
        {isActive && (
          <span
            className={cn(
              "absolute inset-0 animate-ping rounded-full opacity-75",
              config.pulseColor,
            )}
          />
        )}
        <Icon className={cn("relative h-4 w-4", config.color)} />
      </span>
      <span className="font-medium">{message ?? config.label}</span>
    </div>
  )
}
