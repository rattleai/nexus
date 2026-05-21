import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/agents/sessions")({
  beforeLoad: () => {
    throw redirect({ to: "/agents" })
  },
})
