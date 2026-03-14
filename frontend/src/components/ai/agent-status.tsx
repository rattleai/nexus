import {
  Brain,
  Zap,
  Clock,
  AlertCircle,
  CheckCircle,
  Circle,
} from "lucide-react"
import { useTranslation } from "react-i18next"
import { cn } from "@/lib/utils"

export type AgentState = "idle" | "thinking" | "acting" | "waiting" | "error" | "complete"

export interface AgentStatusProps {
  state: AgentState
  message?: string
  className?: string
}

const stateConfig: Record<
  AgentState,
  { icon: React.ElementType; color: string; pulseColor: string; labelKey: string }
> = {
  idle: {
    icon: Circle,
    color: "text-muted-foreground",
    pulseColor: "",
    labelKey: "status.idle",
  },
  thinking: {
    icon: Brain,
    color: "text-purple-500",
    pulseColor: "bg-purple-500/20",
    labelKey: "status.thinking",
  },
  acting: {
    icon: Zap,
    color: "text-blue-500",
    pulseColor: "bg-blue-500/20",
    labelKey: "status.acting",
  },
  waiting: {
    icon: Clock,
    color: "text-yellow-500",
    pulseColor: "bg-yellow-500/20",
    labelKey: "status.waiting",
  },
  error: {
    icon: AlertCircle,
    color: "text-red-500",
    pulseColor: "",
    labelKey: "status.error",
  },
  complete: {
    icon: CheckCircle,
    color: "text-green-500",
    pulseColor: "",
    labelKey: "status.complete",
  },
}

export function AgentStatus({ state, message, className }: AgentStatusProps) {
  const { t: tc } = useTranslation()
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
      <span className="font-medium">{message ?? tc(config.labelKey as never)}</span>
    </div>
  )
}
