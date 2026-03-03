import { createFileRoute } from "@tanstack/react-router"
import { ServiceStatusGrid } from "@/components/dashboard/service-status-grid"
import { GettingStartedCard } from "@/components/dashboard/getting-started-card"

export const Route = createFileRoute("/")({
  component: Dashboard,
})

function Dashboard() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <ServiceStatusGrid />
      <GettingStartedCard />
    </div>
  )
}
