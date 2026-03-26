import { createLazyFileRoute } from "@tanstack/react-router"
import { SessionMainPanel } from "@/components/agents/sessions/session-main-panel"

export const Route = createLazyFileRoute("/agents/$instanceId")({
  component: AgentInstancePage,
})

function AgentInstancePage() {
  const { instanceId } = Route.useParams()
  return <SessionMainPanel instanceId={instanceId} />
}
