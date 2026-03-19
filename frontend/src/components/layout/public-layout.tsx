import { type ReactNode } from "react"
import { Link } from "@tanstack/react-router"
import { LayoutDashboard } from "lucide-react"
import { APP_NAME } from "@/lib/constants"
import { ThemeToggle } from "@/components/theme-toggle"
import { LanguageSwitcher } from "@/components/language-switcher"

interface PublicLayoutProps {
  children: ReactNode
}

export function PublicLayout({ children }: PublicLayoutProps) {
  return (
    <div className="min-h-screen flex flex-col bg-background">
      <header className="flex h-14 items-center justify-between border-b px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2 text-lg font-bold text-primary">
          <LayoutDashboard className="h-5 w-5" />
          <span>{APP_NAME}</span>
        </Link>
        <div className="flex items-center gap-2">
          <LanguageSwitcher />
          <ThemeToggle />
        </div>
      </header>
      <main className="flex-1 flex items-start justify-center p-6">
        <div className="w-full max-w-5xl">
          {children}
        </div>
      </main>
    </div>
  )
}
