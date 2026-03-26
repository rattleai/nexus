import { type ReactNode } from "react"
import { useRouterState } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { Search } from "lucide-react"
import {
  Sidebar,
  SidebarProvider,
  SidebarInset,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { ThemeToggle } from "@/components/theme-toggle"
import { NotificationBell } from "@/components/notification-bell"
import { UserMenu } from "@/components/user-menu"
import { BottomNav } from "@/components/layout/bottom-nav"
import { ConsoleSidebarContent } from "@/components/layout/console-sidebar-content"
import { SettingsSidebarContent } from "@/components/layout/settings-sidebar-content"
import { useIsMobile } from "@/hooks/use-mobile"

const isMac = typeof navigator !== "undefined" && /Mac|iPod|iPhone|iPad/.test(navigator.platform)

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const router = useRouterState()
  const currentPath = router.location.pathname
  const isMobile = useIsMobile()
  const { t } = useTranslation()

  const isSettingsContext = currentPath.startsWith("/settings")

  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:p-4 focus:bg-background focus:text-foreground"
      >
        {t("labels.skip_to_main")}
      </a>
      <Sidebar collapsible="icon">
        {isSettingsContext ? (
          <SettingsSidebarContent currentPath={currentPath} />
        ) : (
          <ConsoleSidebarContent currentPath={currentPath} />
        )}
      </Sidebar>
      <SidebarInset>
        <header className="flex h-14 items-center gap-2 border-b px-4">
          {(!isMobile || isSettingsContext) && <SidebarTrigger />}
          {(!isMobile || isSettingsContext) && <Separator orientation="vertical" className="h-6" />}
          <div className="flex-1" />
          <Button
            variant="outline"
            className="h-8 w-full max-w-sm justify-start gap-2 text-sm text-muted-foreground font-normal px-3"
            onClick={() =>
              document.dispatchEvent(
                new KeyboardEvent("keydown", { key: "k", metaKey: true }),
              )
            }
          >
            <Search className="h-3.5 w-3.5 shrink-0" />
            <span className="hidden sm:inline-flex">{t("labels.search" as never)}</span>
            <kbd className="pointer-events-none ml-auto hidden h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium sm:inline-flex">
              {isMac ? "⌘" : "Ctrl"}K
            </kbd>
          </Button>
          <div className="flex-1" />
          <ThemeToggle />
          <NotificationBell />
          <UserMenu />
        </header>
        <main id="main-content" className="flex-1 flex flex-col min-h-0 p-4 pb-20 sm:p-6 md:pb-6">
          {children}
        </main>
      </SidebarInset>
      <BottomNav />
    </SidebarProvider>
  )
}
