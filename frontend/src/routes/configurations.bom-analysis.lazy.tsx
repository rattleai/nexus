import { createLazyFileRoute } from "@tanstack/react-router"
import { BOMAnalysisPage } from "@/apps/cpq/components/configurations/bom-analysis-page"

export const Route = createLazyFileRoute("/configurations/bom-analysis")({
  component: BOMAnalysisPage,
})
