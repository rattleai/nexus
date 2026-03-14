import { useTranslation } from "react-i18next"
import { Globe, Check } from "lucide-react"
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
  const { i18n, t } = useTranslation()
  const { isAuthenticated } = useAuthContext()

  const currentLang = supportedLanguages.find((l) => l.code === i18n.language)

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
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
          aria-label={t("aria.change_language")}
        >
          <Globe className="h-4 w-4 shrink-0" />
          <span className="truncate">{currentLang?.nativeName ?? i18n.language}</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-48">
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
