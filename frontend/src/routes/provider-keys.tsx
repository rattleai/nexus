import { createFileRoute, redirect } from "@tanstack/react-router"

export const Route = createFileRoute("/provider-keys")({
  beforeLoad: () => {
    throw redirect({ to: "/settings/providers" })
  },
})
