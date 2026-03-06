import type { ReactNode } from "react"
import { Link, useRouterState } from "@tanstack/react-router"
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
import { ThemeToggle } from "@/components/theme-toggle"
import { NotificationBell } from "@/components/notification-bell"
import { UserMenu } from "@/components/user-menu"

const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "0.1.0"

const NAV_GROUPS = [
  {
    label: "Overview",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
    ],
  },
  {
    label: "Platform",
    items: [
      { href: "/jobs", label: "Jobs", icon: Briefcase },
      { href: "/files", label: "Files", icon: FolderOpen },
      { href: "/api-keys", label: "API Keys", icon: Key },
      { href: "/chat", label: "AI Chat", icon: MessageSquare },
    ],
  },
  {
    label: "Organization",
    items: [
      { href: "/billing", label: "Billing", icon: CreditCard },
      { href: "/team", label: "Team", icon: Users },
      { href: "/webhooks", label: "Webhooks", icon: Webhook },
      { href: "/audit-log", label: "Audit Log", icon: Shield },
    ],
  },
  {
    label: "Account",
    items: [
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
]

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const router = useRouterState()
  const currentPath = router.location.pathname

  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:p-4 focus:bg-background focus:text-foreground"
      >
        Skip to main content
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
            <SidebarGroup key={group.label}>
              <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {group.items.map((item) => {
                    const isActive =
                      item.href === "/"
                        ? currentPath === "/"
                        : currentPath.startsWith(item.href)
                    return (
                      <SidebarMenuItem key={item.href}>
                        <SidebarMenuButton asChild isActive={isActive} tooltip={item.label}>
                          <Link to={item.href}>
                            <item.icon className="h-4 w-4" />
                            <span>{item.label}</span>
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
        <SidebarFooter className="p-4">
          <p className="text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
            v{APP_VERSION}
          </p>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="flex h-14 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-6" />
          <div className="flex-1" />
          <ThemeToggle />
          <NotificationBell />
          <UserMenu />
        </header>
        <main id="main-content" className="flex-1 p-6">
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
