import { cn } from "@/lib/utils"
import { Card, CardContent, CardTitle, CardHeader } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

type ServiceStatus = "connected" | "unavailable" | "checking"

interface ServiceStatusCardProps {
  label: string
  status: ServiceStatus
}

const statusConfig = {
  connected: {
    border: "border-green-200",
    dot: "bg-green-500",
    text: "text-green-700",
    label: "Connected",
  },
  unavailable: {
    border: "border-red-200",
    dot: "bg-red-500",
    text: "text-red-700",
    label: "Unavailable",
  },
  checking: {
    border: "border-gray-200",
    dot: "bg-gray-300 animate-pulse",
    text: "text-gray-400",
    label: "Checking\u2026",
  },
} as const

export function ServiceStatusCard({ label, status }: ServiceStatusCardProps) {
  const config = statusConfig[status]

  return (
    <Card className={cn("border", config.border)}>
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent>
        {status === "checking" ? (
          <Skeleton className="h-7 w-24 mt-1" />
        ) : (
          <p className={cn("mt-1 text-lg font-semibold flex items-center", config.text)}>
            <span
              className={cn("inline-block w-2 h-2 rounded-full mr-2", config.dot)}
              aria-hidden="true"
            />
            {config.label}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
