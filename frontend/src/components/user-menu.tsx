import { Link } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { LogOut, Settings, User as UserIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useAuthContext } from "@/lib/auth-context"

export function UserMenu() {
  const { user, logout, isAuthenticated } = useAuthContext()
  const { t } = useTranslation()

  if (!isAuthenticated || !user) {
    return (
      <Button variant="outline" size="sm" asChild>
        <Link to="/login">{t("buttons.sign_in")}</Link>
      </Button>
    )
  }

  const initials = user.display_name
    ? user.display_name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : user.email[0].toUpperCase()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="gap-2" aria-label="User menu">
          <Avatar className="h-6 w-6">
            <AvatarFallback className="text-xs">{initials}</AvatarFallback>
          </Avatar>
          <span className="hidden md:inline text-sm">
            {user.display_name ?? user.email}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          <p className="text-sm font-medium">{user.display_name ?? "User"}</p>
          <p className="text-xs text-muted-foreground">{user.email}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/settings">
            <Settings className="mr-2 h-4 w-4" />
            {t("nav.settings")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to="/api-keys">
            <UserIcon className="mr-2 h-4 w-4" />
            {t("nav.api_keys")}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => logout()} className="text-destructive">
          <LogOut className="mr-2 h-4 w-4" />
          {t("buttons.sign_out")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
