import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Github } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { api } from "@/lib/api-client"

const ALLOWED_PROVIDERS = ["google", "github"] as const

interface SocialLoginButtonsProps {
  mode: "login" | "register"
  disabled?: boolean
}

function GoogleIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4" />
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
    </svg>
  )
}

export function SocialLoginButtons({ mode, disabled }: SocialLoginButtonsProps) {
  const { t } = useTranslation("auth")
  const [providers, setProviders] = useState<string[]>([])
  const [loading, setLoading] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .get("auth/oauth/providers")
      .json<{ providers: string[] }>()
      .then((res) => {
        if (!cancelled) setProviders(res.providers)
      })
      .catch(() => {
        // OAuth not configured — hide buttons
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (providers.length === 0) return null

  const handleOAuth = async (provider: string) => {
    if (!ALLOWED_PROVIDERS.includes(provider as (typeof ALLOWED_PROVIDERS)[number])) return
    setLoading(provider)
    try {
      const res = await api.get(`auth/oauth/${provider}/authorize`).json<{ url: string }>()
      window.location.href = res.url
    } catch {
      setLoading(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <Separator className="w-full" />
        </div>
        <div className="relative flex justify-center text-xs uppercase">
          <span className="bg-card px-2 text-muted-foreground">{t("social.or_continue_with")}</span>
        </div>
      </div>
      <div className="grid gap-2">
        {providers.includes("google") && (
          <Button
            variant="outline"
            className="w-full"
            disabled={disabled || loading !== null}
            onClick={() => handleOAuth("google")}
          >
            <GoogleIcon className="mr-2 h-4 w-4" />
            {mode === "login" ? t("social.google_sign_in") : t("social.google_sign_up")}
          </Button>
        )}
        {providers.includes("github") && (
          <Button
            variant="outline"
            className="w-full"
            disabled={disabled || loading !== null}
            onClick={() => handleOAuth("github")}
          >
            <Github className="mr-2 h-4 w-4" />
            {mode === "login" ? t("social.github_sign_in") : t("social.github_sign_up")}
          </Button>
        )}
      </div>
    </div>
  )
}
