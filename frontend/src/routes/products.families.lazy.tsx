import { createLazyFileRoute } from "@tanstack/react-router"
import { ProductFamilies } from "@/components/products/product-families"

export const Route = createLazyFileRoute("/products/families")({
  component: ProductFamilies,
})
