import { createLazyFileRoute, Navigate } from "@tanstack/react-router"

export const Route = createLazyFileRoute("/agents/sessions")({
  component: () => <Navigate to="/agents" />,
})
