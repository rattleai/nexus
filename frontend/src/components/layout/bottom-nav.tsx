import { Link, useRouterState } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { LayoutDashboard, Bot, MessageSquare, Briefcase, Menu } from "lucide-react"
import { cn } from "@/lib/utils"
import { useIsMobile } from "@/hooks/use-mobile"
import { useSidebar } from "@/components/ui/sidebar"

interface NavItem {
  href: string
  labelKey: string
  icon: React.ComponentType<{ className?: string }>
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/agents", labelKey: "nav.agents", icon: Bot },
  { href: "/chat", labelKey: "nav.ai_chat", icon: MessageSquare },
  { href: "/jobs", labelKey: "nav.jobs", icon: Briefcase },
]

export function BottomNav() {
  const isMobile = useIsMobile()
  const router = useRouterState()
  const currentPath = router.location.pathname
  const { toggleSidebar } = useSidebar()
  const { t } = useTranslation()

  if (!isMobile) return null

  return (
    <nav
      role="navigation"
      aria-label="Primary"
      className="fixed bottom-0 left-0 right-0 z-40 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80"
      style={{ paddingBottom: "var(--safe-area-bottom, 0px)" }}
    >
      <div className="flex h-16 items-stretch justify-around">
        {NAV_ITEMS.map((item) => {
          const isActive =
            item.href === "/" ? currentPath === "/" : currentPath.startsWith(item.href)
          return (
            <Link
              key={item.href}
              to={item.href}
              className={cn(
                "flex flex-1 flex-col items-center justify-center gap-0.5 text-xs transition-colors",
                isActive
                  ? "text-primary font-medium"
                  : "text-muted-foreground hover:text-foreground",
              )}
              aria-current={isActive ? "page" : undefined}
            >
              <item.icon className={cn("h-5 w-5", isActive && "text-primary")} />
              <span>{t(item.labelKey as never)}</span>
            </Link>
          )
        })}
        <button
          type="button"
          onClick={toggleSidebar}
          className="flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          aria-label={t("aria.open_menu")}
        >
          <Menu className="h-5 w-5" />
          <span>{t("nav.more", { defaultValue: "More" })}</span>
        </button>
      </div>
    </nav>
  )
}
