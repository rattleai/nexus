import { createLazyFileRoute, Outlet } from "@tanstack/react-router"

export const Route = createLazyFileRoute("/settings/characteristics")({
  component: CharacteristicsLayout,
})

function CharacteristicsLayout() {
  return <Outlet />
}
