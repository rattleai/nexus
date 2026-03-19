import { type ReactNode } from "react"
import { Link, useRouterState } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import {
  LayoutDashboard,
  Briefcase,
  Key,
  FolderOpen,
  CreditCard,
  Users,
  Webhook,
  Shield,
  Settings,
  MessageSquare,
  Bot,
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
import { Separator } from "@/components/ui/separator"
import { LanguageSwitcher } from "@/components/language-switcher"
import { ThemeToggle } from "@/components/theme-toggle"
import { NotificationBell } from "@/components/notification-bell"
import { UserMenu } from "@/components/user-menu"
import { BottomNav } from "@/components/layout/bottom-nav"
import { useIsMobile } from "@/hooks/use-mobile"

import type { LucideIcon } from "lucide-react"

const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "0.1.0"

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
      { href: "/chat", labelKey: "nav.ai_chat", icon: MessageSquare },
      { href: "/jobs", labelKey: "nav.jobs", icon: Briefcase },
      { href: "/files", labelKey: "nav.files", icon: FolderOpen },
      { href: "/api-keys", labelKey: "nav.api_keys", icon: Key },
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
        <SidebarFooter className="p-4 space-y-2">
          <div className="group-data-[collapsible=icon]:hidden">
            <LanguageSwitcher />
          </div>
          <p className="text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
            v{APP_VERSION}
          </p>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="flex h-14 items-center gap-2 border-b px-4">
          {!isMobile && <SidebarTrigger />}
          {!isMobile && <Separator orientation="vertical" className="h-6" />}
          <div className="flex-1" />
          <ThemeToggle />
          <NotificationBell />
          <UserMenu />
        </header>
        <main id="main-content" className="flex-1 flex flex-col min-h-0 p-6 pb-20 md:pb-6">
          {children}
        </main>
      </SidebarInset>
      <BottomNav />
    </SidebarProvider>
  )
}
