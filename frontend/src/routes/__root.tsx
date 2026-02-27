import { createRootRoute, Outlet } from "@tanstack/react-router"
import { AppShell } from "@/components/layout/app-shell"
import { Toaster } from "sonner"

export const Route = createRootRoute({
  component: RootLayout,
})

function RootLayout() {
  return (
    <AppShell>
      <Outlet />
      <Toaster position="top-right" richColors />
    </AppShell>
  )
}
