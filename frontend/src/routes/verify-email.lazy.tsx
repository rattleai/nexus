import { useEffect, useState } from "react"
import { createLazyFileRoute, Link, useSearch } from "@tanstack/react-router"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { api, parseApiError } from "@/lib/api-client"

export const Route = createLazyFileRoute("/verify-email")({
  component: VerifyEmailPage,
})

function VerifyEmailPage() {
  const { token } = useSearch({ from: "/verify-email" })
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading")
  const [errorMessage, setErrorMessage] = useState("")

  useEffect(() => {
    if (!token) {
      setStatus("error")
      setErrorMessage("Invalid or missing verification token.")
      return
    }

    let cancelled = false

    async function verify() {
      try {
        await api.post("auth/verify-email", { json: { token } })
        if (!cancelled) {
          setStatus("success")
          toast.success("Email verified successfully!")
        }
      } catch (err) {
        if (!cancelled) {
          const apiError = await parseApiError(err)
          setStatus("error")
          setErrorMessage(apiError.detail)
          toast.error("Email verification failed")
        }
      }
    }

    verify()
    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Verify Email</CardTitle>
        </CardHeader>
        <CardContent className="text-center space-y-4">
          {status === "loading" && (
            <div className="flex flex-col items-center gap-3">
              <div
                className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary"
                role="status"
                aria-label="Verifying email"
              />
              <p className="text-sm text-muted-foreground">Verifying your email...</p>
            </div>
          )}
          {status === "success" && (
            <>
              <p className="text-sm text-muted-foreground">
                Your email has been verified successfully.
              </p>
              <Link to="/" className="text-sm text-primary underline">
                Go to Dashboard
              </Link>
            </>
          )}
          {status === "error" && (
            <>
              <p className="text-sm text-destructive" role="alert">
                {errorMessage}
              </p>
              <Link to="/login" className="text-sm text-primary underline">
                Go to Sign In
              </Link>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
