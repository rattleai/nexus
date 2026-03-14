import { Loader2 } from "lucide-react"
import { useTranslation } from "react-i18next"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

interface LoadingStateProps {
  variant?: "spinner" | "skeleton" | "inline"
  message?: string
  rows?: number
  className?: string
}

export function LoadingState({
  variant = "spinner",
  message,
  rows = 3,
  className,
}: LoadingStateProps) {
  const { t } = useTranslation()

  if (variant === "inline") {
    return (
      <span className={cn("inline-flex items-center gap-2 text-muted-foreground", className)}>
        <Loader2 className="h-4 w-4 animate-spin" />
        {message ?? t("labels.loading")}
      </span>
    )
  }

  if (variant === "skeleton") {
    return (
      <div className={cn("space-y-3", className)} aria-busy="true" aria-label={t("labels.loading")}>
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    )
  }

  return (
    <div
      className={cn("flex flex-col items-center justify-center py-12 text-muted-foreground", className)}
      aria-busy="true"
      aria-label={t("labels.loading")}
    >
      <Loader2 className="h-8 w-8 animate-spin" />
      {message && <p className="mt-3 text-sm">{message}</p>}
    </div>
  )
}
