import { createLazyFileRoute, useParams } from "@tanstack/react-router"
import { ConfiguratorPage } from "@/apps/cpq/components/configurator/configurator-layout"

export const Route = createLazyFileRoute("/configurator/$productId")({
  component: ConfiguratorPageRoute,
})

function ConfiguratorPageRoute() {
  const { productId } = useParams({ from: "/configurator/$productId" })
  return <ConfiguratorPage productId={productId} />
}
