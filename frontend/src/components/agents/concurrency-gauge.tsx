import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { Badge } from "@/components/ui/badge"
import { useAgentStore } from "@/stores/agent-store"
import { cn } from "@/lib/utils"

interface ConcurrencyGaugeProps {
  agentName: string
  agentId: string
  runningCount: number
  pendingCount: number
  maxInstances: number // 0 = unlimited
}

const GAUGE_SIZE = 80
const STROKE_WIDTH = 8
const RADIUS = (GAUGE_SIZE - STROKE_WIDTH) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

function getCapacityColor(ratio: number): string {
  if (ratio < 0.5) return "text-emerald-500"
  if (ratio < 0.8) return "text-amber-500"
  return "text-red-500"
}

function getCapacityStroke(ratio: number): string {
  if (ratio < 0.5) return "stroke-emerald-500"
  if (ratio < 0.8) return "stroke-amber-500"
  return "stroke-red-500"
}

export function ConcurrencyGauge({
  agentName,
  agentId,
  runningCount,
  pendingCount,
  maxInstances,
}: ConcurrencyGaugeProps) {
  const selectAgent = useAgentStore((s) => s.selectAgent)
  const setWorkspaceMode = useAgentStore((s) => s.setWorkspaceMode)

  const isUnlimited = maxInstances === 0
  const ratio = isUnlimited
    ? runningCount > 0
      ? Math.min(runningCount / 10, 0.4) // Show modest fill for unlimited
      : 0
    : maxInstances > 0
      ? runningCount / maxInstances
      : 0

  const dashOffset = CIRCUMFERENCE * (1 - Math.min(ratio, 1))
  const colorClass = isUnlimited ? "text-blue-500" : getCapacityColor(ratio)
  const strokeClass = isUnlimited ? "stroke-blue-500" : getCapacityStroke(ratio)

  const handleClick = () => {
    selectAgent(agentId)
    setWorkspaceMode("single")
  }

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={handleClick}
            className={cn(
              "flex flex-col items-center gap-1.5 rounded-lg border p-3",
              "bg-background hover:bg-accent/50 transition-colors",
              "w-[120px] h-[140px] shrink-0",
            )}
          >
            {/* SVG Gauge */}
            <div className="relative">
              <svg
                width={GAUGE_SIZE}
                height={GAUGE_SIZE}
                viewBox={`0 0 ${GAUGE_SIZE} ${GAUGE_SIZE}`}
                className="-rotate-90"
              >
                {/* Background track */}
                <circle
                  cx={GAUGE_SIZE / 2}
                  cy={GAUGE_SIZE / 2}
                  r={RADIUS}
                  fill="none"
                  className="stroke-muted"
                  strokeWidth={STROKE_WIDTH}
                />
                {/* Progress arc */}
                <circle
                  cx={GAUGE_SIZE / 2}
                  cy={GAUGE_SIZE / 2}
                  r={RADIUS}
                  fill="none"
                  className={cn(strokeClass, "transition-all duration-500")}
                  strokeWidth={STROKE_WIDTH}
                  strokeLinecap="round"
                  strokeDasharray={CIRCUMFERENCE}
                  strokeDashoffset={dashOffset}
                />
              </svg>
              {/* Center text */}
              <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className={cn("text-sm font-bold leading-none", colorClass)}>
                  {runningCount}
                </span>
                <span className="text-[10px] text-muted-foreground leading-tight">
                  /{isUnlimited ? "\u221E" : maxInstances}
                </span>
              </div>
            </div>

            {/* Agent name */}
            <span className="text-xs font-medium truncate w-full text-center leading-tight">
              {agentName}
            </span>

            {/* Pending badge */}
            {pendingCount > 0 && (
              <Badge
                variant="secondary"
                className="h-4 px-1.5 text-[10px] leading-none"
              >
                {pendingCount} pending
              </Badge>
            )}
          </button>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs">
          <div className="space-y-0.5">
            <div className="font-medium">{agentName}</div>
            <div className="text-muted-foreground">
              {runningCount} running
              {pendingCount > 0 && `, ${pendingCount} pending`}
              {" / "}
              {isUnlimited ? "unlimited" : `${maxInstances} max`}
            </div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
