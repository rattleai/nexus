import { useHealth } from "@/hooks/use-health"
import { ServiceStatusCard } from "./service-status-card"

const services = [
  { key: "db", label: "Database" },
  { key: "redis", label: "Redis" },
  { key: "storage", label: "Storage" },
] as const

export function ServiceStatusGrid() {
  const { data, isLoading } = useHealth()

  return (
    <div
      className="grid grid-cols-1 sm:grid-cols-3 gap-4"
      role="status"
      aria-label="Service health status"
    >
      {services.map(({ key, label }) => {
        let status: "connected" | "unavailable" | "checking" = "checking"
        if (!isLoading && data) {
          status = data.services[key] ? "connected" : "unavailable"
        }
        return <ServiceStatusCard key={key} label={label} status={status} />
      })}
    </div>
  )
}
