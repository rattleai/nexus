import type { ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { NavLink } from "./nav-link"

const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "0.1.0"

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen flex flex-col">
      <nav className="bg-surface border-b border-gray-200 shadow-nav" aria-label="Main navigation">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <Link to="/" className="text-xl font-bold text-brand-600">
              SaaS Platform
            </Link>
            <div className="flex items-center gap-4">
              <NavLink href="/" label="Dashboard" />
              <NavLink href="/jobs" label="Jobs" />
              <NavLink href="/api-keys" label="API Keys" />
              <NavLink href="/settings" label="Settings" />
            </div>
          </div>
        </div>
      </nav>

      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>

      <footer className="border-t border-gray-200 py-4 text-center text-sm text-gray-500">
        SaaS Platform v{APP_VERSION}
      </footer>
    </div>
  )
}
