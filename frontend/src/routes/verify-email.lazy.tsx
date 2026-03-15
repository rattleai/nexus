import { useEffect, useState } from "react"
import { createLazyFileRoute, Link, useSearch } from "@tanstack/react-router"
import { useTranslation } from "react-i18next"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api, parseApiError } from "@/lib/api-client"

export const Route = createLazyFileRoute("/verify-email")({
  component: VerifyEmailPage,
})

function VerifyEmailPage() {
  const { t } = useTranslation("auth")
  const { token } = useSearch({ from: "/verify-email" })
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading")
  const [errorMessage, setErrorMessage] = useState("")

  useEffect(() => {
    if (!token) {
      setStatus("error")
      setErrorMessage(t("verify_email.invalid_token"))
      return
    }

    let cancelled = false

    async function verify() {
      try {
        await api.post("auth/verify-email", { json: { token } })
        if (!cancelled) {
          setStatus("success")
          toast.success(t("verify_email.success_toast"))
        }
      } catch (err) {
        if (!cancelled) {
          const apiError = await parseApiError(err)
          setStatus("error")
          setErrorMessage(apiError.detail)
          toast.error(t("verify_email.failed"))
        }
      }
    }

    verify()
    return () => {
      cancelled = true
    }
  }, [token, t])

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("verify_email.title")}</CardTitle>
        </CardHeader>
        <CardContent className="text-center space-y-4">
          {status === "loading" && (
            <div className="flex flex-col items-center gap-3">
              <div
                className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary"
                role="status"
                aria-label={t("verify_email.verifying")}
              />
              <p className="text-sm text-muted-foreground">{t("verify_email.verifying")}</p>
            </div>
          )}
          {status === "success" && (
            <>
              <p className="text-sm text-muted-foreground">
                {t("verify_email.success")}
              </p>
              <Link to="/" className="text-sm text-primary underline">
                {t("verify_email.go_to_dashboard")}
              </Link>
            </>
          )}
          {status === "error" && (
            <>
              <p className="text-sm text-destructive" role="alert">
                {errorMessage}
              </p>
              <Link to="/login" className="text-sm text-primary underline">
                {t("verify_email.go_to_sign_in")}
              </Link>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
