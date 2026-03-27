import { createLazyFileRoute } from "@tanstack/react-router"
import { ProductFamilies } from "@/apps/cpq/components/products/product-families"

export const Route = createLazyFileRoute("/products/families")({
  component: ProductFamilies,
})
