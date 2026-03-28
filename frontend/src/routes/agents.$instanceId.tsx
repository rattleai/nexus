import { createFileRoute } from "@tanstack/react-router"

interface AgentInstanceSearch {
  session?: string
}

export const Route = createFileRoute("/agents/$instanceId")({
  validateSearch: (search: Record<string, unknown>): AgentInstanceSearch => ({
    session: typeof search.session === "string" ? search.session : undefined,
  }),
})
