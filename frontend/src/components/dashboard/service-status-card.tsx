import { useTranslation } from "react-i18next"
import { cn } from "@/lib/utils"
import { Card, CardContent, CardTitle, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

type ServiceStatus = "connected" | "unavailable" | "checking"

interface ServiceStatusCardProps {
  label: string
  status: ServiceStatus
}

const statusStyles = {
  connected: {
    border: "border-green-200",
    dot: "bg-green-500",
    text: "text-green-700",
  },
  unavailable: {
    border: "border-red-200",
    dot: "bg-red-500",
    text: "text-red-700",
  },
  checking: {
    border: "border-gray-200",
    dot: "bg-gray-300 animate-pulse",
    text: "text-gray-400",
  },
} as const

const statusLabelKeys = {
  connected: "status.connected",
  unavailable: "status.unavailable",
  checking: "status.checking",
} as const

export function ServiceStatusCard({ label, status }: ServiceStatusCardProps) {
  const { t } = useTranslation()
  const styles = statusStyles[status]

  return (
    <Card className={cn("border", styles.border)}>
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent>
        {status === "checking" ? (
          <Skeleton className="h-7 w-24 mt-1" />
        ) : (
          <p className={cn("mt-1 text-lg font-semibold flex items-center", styles.text)}>
            <span
              className={cn("inline-block w-2 h-2 rounded-full mr-2", styles.dot)}
              aria-hidden="true"
            />
            {t(statusLabelKeys[status])}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
