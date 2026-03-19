import { useEffect, useState } from "react"
import { createLazyFileRoute, Link, useNavigate, useParams, useSearch } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { Loader2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useAuthContext } from "@/lib/auth-context"
import { api, setAccessToken } from "@/lib/api-client"

export const Route = createLazyFileRoute("/auth/callback/$provider")({
  component: OAuthCallbackPage,
})

function OAuthCallbackPage() {
  const { provider } = useParams({ from: "/auth/callback/$provider" })
  const navigate = useNavigate()
  const { t } = useTranslation("auth")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get("code")
    const state = params.get("state")

    if (!code || !state) {
      setError(t("social.callback_missing_params"))
      return
    }

    let cancelled = false

    async function handleCallback() {
      try {
        const res = await api
          .post(`auth/oauth/${provider}/callback`, {
            json: { code, state },
            credentials: "include",
          })
          .json<{ access_token: string; user: Record<string, unknown> }>()

        if (cancelled) return

        setAccessToken(res.access_token)
        window.dispatchEvent(new Event("auth-change"))
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
  }, [provider, navigate, t])

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
