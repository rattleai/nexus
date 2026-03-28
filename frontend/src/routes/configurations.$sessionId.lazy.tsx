import { createLazyFileRoute, useParams } from "@tanstack/react-router"
import { ConfigurationDetail } from "@/apps/cpq/components/configurations/configuration-detail"

export const Route = createLazyFileRoute("/configurations/$sessionId")({
  component: ConfigurationDetailLayout,
})

function ConfigurationDetailLayout() {
  const { sessionId } = useParams({ from: "/configurations/$sessionId" })
  return <ConfigurationDetail sessionId={sessionId} />
}
