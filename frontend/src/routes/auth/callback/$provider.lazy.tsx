import { useEffect, useRef, useState } from "react"
import { createLazyFileRoute, Link, useNavigate, useParams } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { Loader2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useAuthContext } from "@/lib/auth-context"

const ALLOWED_PROVIDERS = ["google", "github"] as const

export const Route = createLazyFileRoute("/auth/callback/$provider")({
  component: OAuthCallbackPage,
})

function OAuthCallbackPage() {
  const { provider } = useParams({ from: "/auth/callback/$provider" })
  const navigate = useNavigate()
  const { t } = useTranslation("auth")
  const { loginWithOAuth } = useAuthContext()
  const [error, setError] = useState<string | null>(null)
  const hasSubmitted = useRef(false)

  useEffect(() => {
    if (hasSubmitted.current) return
    hasSubmitted.current = true

    // Validate provider against allowlist
    if (!ALLOWED_PROVIDERS.includes(provider as (typeof ALLOWED_PROVIDERS)[number])) {
      setError(t("social.callback_error"))
      return
    }

    const params = new URLSearchParams(window.location.search)
    const code = params.get("code")
    const state = params.get("state")

    // Clear query params to prevent back-button resubmission
    history.replaceState({}, "", window.location.pathname)

    if (!code || !state) {
      setError(t("social.callback_missing_params"))
      return
    }

    let cancelled = false

    async function handleCallback() {
      try {
        await loginWithOAuth(provider, code!, state!)
        if (cancelled) return
        navigate({ to: "/" })
      } catch {
        if (!cancelled) {
          setError(t("social.callback_error"))
        }
      }
    }

    handleCallback()
    return () => {
      cancelled = true
    }
  }, [provider, navigate, t, loginWithOAuth])

  if (error) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>{t("social.callback_title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-center">
            <p className="text-sm text-destructive">{error}</p>
            <Button asChild variant="outline">
              <Link to="/login">{t("social.back_to_login")}</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("social.callback_title")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">{t("social.callback_description")}</p>
        </CardContent>
      </Card>
    </div>
  )
}
