import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

type PlanStatus = "active" | "past_due" | "canceled" | "trialing"

interface PlanBadgeProps {
  plan: string
  status?: PlanStatus
  className?: string
}

const statusStyles: Record<PlanStatus, string> = {
  active: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  trialing: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  past_due: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  canceled: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
}

const statusLabels: Record<PlanStatus, string> = {
  active: "Active",
  trialing: "Trial",
  past_due: "Past Due",
  canceled: "Canceled",
}

export function PlanBadge({ plan, status, className }: PlanBadgeProps) {
  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      <Badge variant="secondary">{plan}</Badge>
      {status && (
        <Badge
          variant="outline"
          className={cn("border-transparent", statusStyles[status])}
        >
          {statusLabels[status]}
        </Badge>
      )}
    </div>
  )
}
