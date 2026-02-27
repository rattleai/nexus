import { createRootRoute, Outlet, type ErrorComponentProps } from "@tanstack/react-router"
import { AppShell } from "@/components/layout/app-shell"
import { Toaster } from "sonner"

function RootErrorComponent({ error }: ErrorComponentProps) {
  return (
    <div role="alert" className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-md text-center">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Something went wrong</h1>
        <p className="text-gray-600">{error?.message ?? "An unexpected error occurred."}</p>
      </div>
    </div>
  )
}

function NotFoundComponent() {
  return (
    <div className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-md text-center">
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Page not found</h1>
        <p className="text-gray-600">The page you're looking for doesn't exist.</p>
      </div>
    </div>
  )
}

export const Route = createRootRoute({
  component: RootLayout,
  errorComponent: RootErrorComponent,
  notFoundComponent: NotFoundComponent,
})

function RootLayout() {
  return (
    <AppShell>
      <Outlet />
      <Toaster position="top-right" richColors />
    </AppShell>
  )
}
