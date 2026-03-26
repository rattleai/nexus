import { createLazyFileRoute } from "@tanstack/react-router"
import { BOMAnalysisPage } from "@/components/configurations/bom-analysis-page"

export const Route = createLazyFileRoute("/configurations/bom-analysis")({
  component: BOMAnalysisPage,
})
