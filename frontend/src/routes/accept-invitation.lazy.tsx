import { useState } from "react"
import { createLazyFileRoute, Link, useNavigate, useSearch } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api, parseApiError } from "@/lib/api-client"

export const Route = createLazyFileRoute("/accept-invitation")({
  component: AcceptInvitationPage,
})

function AcceptInvitationPage() {
  const { token } = useSearch({ from: "/accept-invitation" })
  const navigate = useNavigate()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState("")
  const { t } = useTranslation("team")

  if (!token) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>{t("accept_invitation.title")}</CardTitle>
          </CardHeader>
          <CardContent className="text-center space-y-4">
            <p className="text-sm text-destructive" role="alert">
              {t("accept_invitation.invalid_token")}
            </p>
            <Link to="/login" className="text-sm text-primary underline">
              {t("accept_invitation.go_to_sign_in")}
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  const handleAccept = async () => {
    setIsSubmitting(true)
    setError("")
    try {
      await api.post("auth/accept-invitation", { json: { token } })
      toast.success(t("accept_invitation.success"))
      navigate({ to: "/" })
    } catch (err) {
      const apiError = await parseApiError(err)
      setError(apiError.detail)
      toast.error(t("accept_invitation.error"))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("accept_invitation.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            {t("accept_invitation.description")}
          </p>
          <Button
            className="w-full"
            onClick={handleAccept}
            disabled={isSubmitting}
            aria-busy={isSubmitting}
          >
            {isSubmitting ? t("accept_invitation.accepting") : t("accept_invitation.accept")}
          </Button>
          <p className="text-sm text-center text-muted-foreground">
            <Link to="/login" className="text-primary underline">
              {t("accept_invitation.back_to_sign_in")}
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
