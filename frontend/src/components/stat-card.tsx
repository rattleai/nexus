import type { LucideIcon } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface StatCardProps {
  title: string
  value: string | number
  description?: string
  icon?: LucideIcon
  trend?: { value: number; label?: string }
  className?: string
}

export function StatCard({
  title,
  value,
  description,
  icon: Icon,
  trend,
  className,
}: StatCardProps) {
  return (
    <Card className={cn(className)}>
      <CardContent className="p-6">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
        </div>
        <div className="mt-2">
          <p className="text-2xl font-bold">{value}</p>
          {(description || trend) && (
            <p className="mt-1 text-xs text-muted-foreground">
              {trend && (
                <span
                  className={cn(
                    "font-medium mr-1",
                    trend.value > 0 && "text-emerald-600 dark:text-emerald-400",
                    trend.value < 0 && "text-red-600 dark:text-red-400",
                  )}
                >
                  {trend.value > 0 ? "+" : ""}
                  {trend.value}%
                </span>
              )}
              {description ?? trend?.label}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
