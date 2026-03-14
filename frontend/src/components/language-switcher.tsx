import { useTranslation } from "react-i18next"
import { Globe, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { supportedLanguages } from "@/lib/i18n"
import { useAuthContext } from "@/lib/auth-context"
import { api } from "@/lib/api-client"

export function LanguageSwitcher() {
  const { i18n } = useTranslation()
  const { isAuthenticated } = useAuthContext()

  const changeLanguage = async (lng: string) => {
    await i18n.changeLanguage(lng)

    // Persist to user profile if authenticated
    if (isAuthenticated) {
      try {
        await api.patch("auth/me", { json: { locale: lng } })
      } catch {
        // Silently fail — language still changes locally
      }
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" aria-label="Change language">
          <Globe className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {supportedLanguages.map((lang) => (
          <DropdownMenuItem
            key={lang.code}
            onClick={() => changeLanguage(lang.code)}
            className="flex items-center justify-between gap-3"
          >
            <span className="flex items-center gap-2">
              <span className="font-medium">{lang.nativeName}</span>
              {lang.nativeName !== lang.name && (
                <span className="text-muted-foreground text-xs">{lang.name}</span>
              )}
            </span>
            {i18n.language === lang.code && <Check className="h-4 w-4 text-primary" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
