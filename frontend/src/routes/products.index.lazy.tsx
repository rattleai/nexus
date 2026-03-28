import { createLazyFileRoute } from "@tanstack/react-router"
import { ProductList } from "@/apps/cpq/components/products/product-list"

export const Route = createLazyFileRoute("/products/")({
  component: ProductList,
})
