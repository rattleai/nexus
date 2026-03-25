import { createLazyFileRoute } from "@tanstack/react-router"
import { AgentSessionsPage } from "@/components/agents/sessions/agent-sessions-page"

export const Route = createLazyFileRoute("/agents/")({
  component: AgentSessionsPage,
})
