import { createLazyFileRoute } from "@tanstack/react-router"
import { SessionEmptyState } from "@/components/agents/sessions/session-empty-state"

export const Route = createLazyFileRoute("/agents/")({
  component: AgentsIndexPage,
})

function AgentsIndexPage() {
  return <SessionEmptyState />
}
