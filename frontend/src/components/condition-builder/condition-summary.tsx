import { cn } from "@/lib/utils"
import type { Characteristic } from "@/types/configurator"
import type { ConditionNode } from "./condition-types"
import { conditionToSummary } from "./condition-utils"

interface ConditionSummaryProps {
  condition: ConditionNode | null
  characteristics: Characteristic[]
  className?: string
}

export function ConditionSummary({
  condition,
  characteristics,
  className,
}: ConditionSummaryProps) {
  const summary = conditionToSummary(condition, characteristics)
  const isEmpty = condition === null

  return (
    <span
      className={cn(
        "text-sm",
        isEmpty ? "text-muted-foreground italic" : "text-foreground",
        className,
      )}
    >
      {summary}
    </span>
  )
}
