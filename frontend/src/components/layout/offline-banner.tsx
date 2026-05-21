import { WifiOff } from "lucide-react"
import { useTranslation } from "react-i18next"
import { useOnlineStatus } from "@/hooks/use-online-status"

export function OfflineBanner() {
  const isOnline = useOnlineStatus()
  const { t } = useTranslation()

  if (isOnline) return null

  return (
    <div
      role="status"
      aria-live="assertive"
      className="fixed top-[var(--safe-area-top,0px)] left-0 right-0 z-50 flex items-center justify-center gap-2 bg-amber-600 px-4 py-2 text-sm font-medium text-white"
    >
      <WifiOff className="h-4 w-4 shrink-0" />
      <span>{t("offline_banner")}</span>
    </div>
  )
}
