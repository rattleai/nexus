import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/agents/workspace")({
  beforeLoad: () => {
    throw redirect({ to: "/settings/agents" })
  },
})
