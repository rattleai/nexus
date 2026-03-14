import { useTranslation } from "react-i18next"
import { AlertCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface ErrorStateProps {
  title?: string
  message?: string
  onRetry?: () => void
  className?: string
}

export function ErrorState({
  title,
  message,
  onRetry,
  className,
}: ErrorStateProps) {
  const { t } = useTranslation()

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center py-12 text-center",
        className,
      )}
    >
      <AlertCircle className="h-10 w-10 text-destructive mb-3" />
      <h3 className="text-lg font-semibold text-foreground">{title ?? t("error_state.default_title")}</h3>
      <p className="mt-1 text-sm text-muted-foreground max-w-sm">{message ?? t("error_state.default_message")}</p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry}>
          {t("buttons.try_again")}
        </Button>
      )}
    </div>
  )
}
