import { Circle } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"

export interface TimelineItem {
  id: string
  title: string
  description?: string
  date?: string
  icon?: LucideIcon
  variant?: "default" | "success" | "warning" | "error"
}

interface TimelineProps {
  items: TimelineItem[]
  className?: string
}

const variantStyles: Record<
  NonNullable<TimelineItem["variant"]>,
  string
> = {
  default: "border-muted-foreground/30 text-muted-foreground",
  success: "border-green-500 text-green-500 bg-green-500/10",
  warning: "border-yellow-500 text-yellow-500 bg-yellow-500/10",
  error: "border-red-500 text-red-500 bg-red-500/10",
}

export function Timeline({ items, className }: TimelineProps) {
  return (
    <div className={cn("relative", className)} role="list">
      {items.map((item, index) => {
        const Icon = item.icon ?? Circle
        const variant = item.variant ?? "default"
        const isLast = index === items.length - 1

        return (
          <div
            key={item.id}
            className="relative flex gap-4 pb-8 last:pb-0"
            role="listitem"
          >
            {/* Vertical connector line */}
            {!isLast && (
              <div
                className="absolute left-[15px] top-8 h-[calc(100%-2rem)] w-px bg-border"
                aria-hidden="true"
              />
            )}

            {/* Dot / Icon */}
            <div
              className={cn(
                "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 bg-background",
                variantStyles[variant],
              )}
              aria-hidden="true"
            >
              <Icon className="h-3.5 w-3.5" />
            </div>

            {/* Content */}
            <div className="flex-1 pt-0.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-foreground">
                  {item.title}
                </p>
                {item.date && (
                  <time
                    dateTime={item.date}
                    className="shrink-0 text-xs text-muted-foreground"
                  >
                    {item.date}
                  </time>
                )}
              </div>
              {item.description && (
                <p className="mt-1 text-sm text-muted-foreground">
                  {item.description}
                </p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
