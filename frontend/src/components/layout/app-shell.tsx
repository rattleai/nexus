import { type ReactNode } from "react"
import { Link, useRouterState } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import {
  LayoutDashboard,
  Briefcase,
  Key,
  KeyRound,
  FolderOpen,
  CreditCard,
  Users,
  Webhook,
  Shield,
  Settings,
  MessageSquare,
  Bot,
  Activity,
  Code2,
  Search,
} from "lucide-react"
import { APP_NAME } from "@/lib/constants"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarInset,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { NotificationBell } from "@/components/notification-bell"
import { UserMenu } from "@/components/user-menu"
import { BottomNav } from "@/components/layout/bottom-nav"
import { useIsMobile } from "@/hooks/use-mobile"

import type { LucideIcon } from "lucide-react"

const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "0.1.0"
const isMac = typeof navigator !== "undefined" && /Mac|iPod|iPhone|iPad/.test(navigator.platform)

interface NavItem {
  href: string
  labelKey: string
  icon: LucideIcon
}

interface NavGroup {
  labelKey: string
  items: NavItem[]
}

const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: "nav.overview",
    items: [
      { href: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
    ],
  },
  {
    labelKey: "nav.platform",
    items: [
      { href: "/agents", labelKey: "nav.agents", icon: Bot },
      { href: "/agents/sessions", labelKey: "nav.agent_sessions", icon: Activity },
      { href: "/chat", labelKey: "nav.ai_chat", icon: MessageSquare },
      { href: "/jobs", labelKey: "nav.jobs", icon: Briefcase },
      { href: "/files", labelKey: "nav.files", icon: FolderOpen },
      { href: "/api-keys", labelKey: "nav.api_keys", icon: Key },
      { href: "/provider-keys", labelKey: "nav.provider_keys", icon: KeyRound },
    ],
  },
  {
    labelKey: "nav.organization",
    items: [
      { href: "/billing", labelKey: "nav.billing", icon: CreditCard },
      { href: "/team", labelKey: "nav.team", icon: Users },
      { href: "/webhooks", labelKey: "nav.webhooks", icon: Webhook },
      { href: "/audit-log", labelKey: "nav.audit_log", icon: Shield },
    ],
  },
  {
    labelKey: "nav.account",
    items: [
      { href: "/settings", labelKey: "nav.settings", icon: Settings },
    ],
  },
]

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const router = useRouterState()
  const currentPath = router.location.pathname
  const isMobile = useIsMobile()
  const { t } = useTranslation()

  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:p-4 focus:bg-background focus:text-foreground"
      >
        {t("labels.skip_to_main")}
      </a>
      <Sidebar collapsible="icon">
        <SidebarHeader className="p-4">
          <Link to="/" className="flex items-center gap-2 text-lg font-bold text-primary">
            <LayoutDashboard className="h-5 w-5" />
            <span className="group-data-[collapsible=icon]:hidden">{APP_NAME}</span>
          </Link>
        </SidebarHeader>
        <SidebarContent>
          {NAV_GROUPS.map((group) => (
            <SidebarGroup key={group.labelKey}>
              <SidebarGroupLabel>{t(group.labelKey as never)}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {group.items.map((item) => {
                    const isActive =
                      item.href === "/"
                        ? currentPath === "/"
                        : item.href === "/agents"
                          ? currentPath === "/agents" || currentPath === "/agents/"
                          : currentPath.startsWith(item.href)
                    const label = t(item.labelKey as never) as string
                    return (
                      <SidebarMenuItem key={item.href}>
                        <SidebarMenuButton asChild isActive={isActive} tooltip={label}>
                          <Link to={item.href}>
                            <item.icon className="h-4 w-4" />
                            <span>{label}</span>
                          </Link>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    )
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}

        </SidebarContent>
        <SidebarFooter className="p-3 space-y-2">
          <div className="group-data-[collapsible=icon]:hidden">
            <LanguageSwitcher />
          </div>
          <Link
            to="/developers"
            data-active={currentPath.startsWith("/developers") || undefined}
            className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground data-[active]:bg-primary/10 data-[active]:text-primary"
          >
            <Code2 className="h-4 w-4 shrink-0" />
            <span className="flex-1 group-data-[collapsible=icon]:hidden">
              {t("nav.developers" as never)}
            </span>
            <span className="text-[10px] font-normal text-muted-foreground/60 tabular-nums group-data-[collapsible=icon]:hidden">
              v{APP_VERSION}
            </span>
          </Link>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="flex h-14 items-center gap-2 border-b px-4">
          {!isMobile && <SidebarTrigger />}
          {!isMobile && <Separator orientation="vertical" className="h-6" />}
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
