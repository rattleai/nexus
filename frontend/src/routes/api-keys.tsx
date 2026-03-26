import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/api-keys")({
  beforeLoad: () => {
    throw redirect({ to: "/settings/api-keys" })
  },
})
