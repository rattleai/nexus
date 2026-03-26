import { Link } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { LayoutDashboard, Bot, Code2, Package, ClipboardList } from "lucide-react"
import { APP_NAME } from "@/lib/constants"
import {
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { LanguageSwitcher } from "@/components/language-switcher"

import type { LucideIcon } from "lucide-react"

const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "0.1.0"

interface NavItem {
  href: string
  labelKey: string
  icon: LucideIcon
}

const CONSOLE_NAV_ITEMS: NavItem[] = [
  { href: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/agents", labelKey: "nav.agents", icon: Bot },
  { href: "/products", labelKey: "nav.products", icon: Package },
  { href: "/configurations", labelKey: "nav.configurations", icon: ClipboardList },
]

interface ConsoleSidebarContentProps {
  currentPath: string
}

export function ConsoleSidebarContent({ currentPath }: ConsoleSidebarContentProps) {
  const { t } = useTranslation()

  return (
    <>
      <SidebarHeader className="p-4">
        <Link to="/" className="flex items-center gap-2 text-lg font-bold text-primary">
          <LayoutDashboard className="h-5 w-5" />
          <span className="group-data-[collapsible=icon]:hidden">{APP_NAME}</span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {CONSOLE_NAV_ITEMS.map((item) => {
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
    </>
  )
}
