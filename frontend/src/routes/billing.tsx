import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/billing")({
  beforeLoad: () => {
    throw redirect({ to: "/settings/billing" })
  },
})
