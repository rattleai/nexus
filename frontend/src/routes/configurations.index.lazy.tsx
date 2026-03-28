import { createLazyFileRoute } from "@tanstack/react-router"
import { ConfigurationsList } from "@/apps/cpq/components/configurations/configurations-list"

export const Route = createLazyFileRoute("/configurations/")({
  component: ConfigurationsList,
})
