import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/audit-log")({
  beforeLoad: () => {
    throw redirect({ to: "/settings/audit-log" })
  },
})
