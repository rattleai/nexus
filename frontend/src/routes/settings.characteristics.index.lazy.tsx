import { createLazyFileRoute } from "@tanstack/react-router"
import { CharacteristicsLibrary } from "@/apps/cpq/components/settings/characteristics-library"

export const Route = createLazyFileRoute("/settings/characteristics/")({
  component: CharacteristicsLibrary,
})
