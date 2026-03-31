import { createLazyFileRoute, useParams } from "@tanstack/react-router"
import { ProductDetail } from "@/apps/cpq/components/products/product-detail"

export const Route = createLazyFileRoute("/products/$productId")({
  component: ProductDetailLayout,
})

function ProductDetailLayout() {
  const { productId } = useParams({ from: "/products/$productId" })
  return <ProductDetail productId={productId} />
}
