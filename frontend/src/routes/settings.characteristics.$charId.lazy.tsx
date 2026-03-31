import { createLazyFileRoute, useParams } from "@tanstack/react-router"
import { CharacteristicDetail } from "@/components/settings/characteristic-detail"

export const Route = createLazyFileRoute("/settings/characteristics/$charId")({
  component: CharacteristicDetailLayout,
})

function CharacteristicDetailLayout() {
  const { charId } = useParams({ from: "/settings/characteristics/$charId" })
  return <CharacteristicDetail charId={charId} />
}
