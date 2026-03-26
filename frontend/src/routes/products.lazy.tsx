import { createLazyFileRoute, Outlet } from "@tanstack/react-router"
import { AuthGuard } from "@/components/auth/auth-guard"

export const Route = createLazyFileRoute("/products")({
  component: ProductsLayout,
})

function ProductsLayout() {
  return (
    <AuthGuard>
      <Outlet />
    </AuthGuard>
  )
}
