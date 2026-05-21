import { cn } from "@/lib/utils"

type StatusDotVariant = "active" | "inactive" | "draft" | "disabled" | "error"
type StatusDotSize = "sm" | "md" | "lg"

const colors: Record<StatusDotVariant, { dot: string; ping: string }> = {
  active: { dot: "bg-green-500", ping: "bg-green-300" },
  draft: { dot: "bg-yellow-500", ping: "bg-yellow-300" },
  disabled: { dot: "bg-red-500", ping: "bg-red-300" },
  error: { dot: "bg-red-500", ping: "bg-red-300" },
  inactive: { dot: "bg-slate-700 dark:bg-slate-400", ping: "bg-slate-400" },
}

const sizes: Record<StatusDotSize, string> = {
  sm: "h-2 w-2",
  md: "h-2.5 w-2.5",
  lg: "h-3 w-3",
}

interface StatusDotProps {
  variant: StatusDotVariant
  size?: StatusDotSize
  pulse?: boolean
  label?: string
  className?: string
  labelClassName?: string
}

export function StatusDot({
  variant,
  size = "md",
  pulse,
  label,
  className,
  labelClassName,
}: StatusDotProps) {
  const c = colors[variant] ?? colors.inactive
  const s = sizes[size]
  const shouldPulse = pulse ?? (variant === "active" || variant === "draft" || variant === "error")

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="relative inline-flex items-center shrink-0">
        {shouldPulse && (
          <span
            className={cn(
              "absolute inline-flex rounded-full opacity-75 animate-ping",
              s,
              c.ping,
            )}
          />
        )}
        <span className={cn("relative inline-flex rounded-full", s, c.dot)} />
      </span>
      {label && (
        <span
          className={cn(
            "text-sm text-slate-700 dark:text-slate-300",
            labelClassName,
          )}
        >
          {label}
        </span>
      )}
    </div>
  )
}

/** Map common status strings to StatusDot variants. */
export function statusToVariant(status: string): StatusDotVariant {
  switch (status) {
    case "active":
      return "active"
    case "draft":
      return "draft"
    case "disabled":
      return "disabled"
    case "error":
    case "failed":
      return "error"
    default:
      return "inactive"
  }
}
