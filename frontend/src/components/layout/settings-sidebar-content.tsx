import { Link } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import {
  ArrowLeft,
  User,
  Bot,
  KeyRound,
  Key,
  Webhook,
  Plug,
  Users,
  CreditCard,
  Shield,
  Lock,
  Download,
  AlertTriangle,
} from "lucide-react"
import {
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"

import type { LucideIcon } from "lucide-react"

interface NavItem {
  href: string
  labelKey: string
  icon: LucideIcon
}

interface NavGroup {
  labelKey: string
  items: NavItem[]
}

const SETTINGS_NAV_GROUPS: NavGroup[] = [
  {
    labelKey: "settings_nav.general",
    items: [
      { href: "/settings/general", labelKey: "settings_nav.profile_language", icon: User },
    ],
  },
  {
    labelKey: "settings_nav.agents",
    items: [
      { href: "/settings/agents", labelKey: "settings_nav.agent_definitions", icon: Bot },
      { href: "/settings/providers", labelKey: "settings_nav.provider_keys", icon: KeyRound },
    ],
  },
  {
    labelKey: "settings_nav.integrations",
    items: [
      { href: "/settings/connectors", labelKey: "settings_nav.connectors", icon: Plug },
      { href: "/settings/api-keys", labelKey: "settings_nav.api_keys", icon: Key },
      { href: "/settings/webhooks", labelKey: "settings_nav.webhooks", icon: Webhook },
    ],
  },
  {
    labelKey: "settings_nav.organization",
    items: [
      { href: "/settings/team", labelKey: "settings_nav.team", icon: Users },
      { href: "/settings/billing", labelKey: "settings_nav.billing", icon: CreditCard },
      { href: "/settings/audit-log", labelKey: "settings_nav.audit_log", icon: Shield },
    ],
  },
  {
    labelKey: "settings_nav.account_section",
    items: [
      { href: "/settings/security", labelKey: "settings_nav.security", icon: Lock },
      { href: "/settings/data", labelKey: "settings_nav.data_export", icon: Download },
      { href: "/settings/danger", labelKey: "settings_nav.danger_zone", icon: AlertTriangle },
    ],
  },
]

interface SettingsSidebarContentProps {
  currentPath: string
}

export function SettingsSidebarContent({ currentPath }: SettingsSidebarContentProps) {
  const { t } = useTranslation()

  return (
    <>
      <SidebarHeader className="p-4">
        <Link
          to="/"
          className="flex items-center gap-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          <span className="group-data-[collapsible=icon]:hidden">
            {t("settings_nav.back_to_console" as never)}
          </span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        {SETTINGS_NAV_GROUPS.map((group) => (
          <SidebarGroup key={group.labelKey}>
            <SidebarGroupLabel>{t(group.labelKey as never)}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => {
                  const isActive = currentPath.startsWith(item.href)
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
      <SidebarFooter className="p-3" />
    </>
  )
}
