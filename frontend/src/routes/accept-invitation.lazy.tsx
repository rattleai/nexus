import { useState } from "react"
import { createLazyFileRoute, Link, useNavigate, useSearch } from "@tanstack/react-router"
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

  if (!token) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>Accept Invitation</CardTitle>
          </CardHeader>
          <CardContent className="text-center space-y-4">
            <p className="text-sm text-destructive" role="alert">
              Invalid or missing invitation token.
            </p>
            <Link to="/login" className="text-sm text-primary underline">
              Go to Sign In
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
      toast.success("Invitation accepted!")
      navigate({ to: "/" })
    } catch (err) {
      const apiError = await parseApiError(err)
      setError(apiError.detail)
      toast.error("Failed to accept invitation")
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Accept Invitation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <p className="text-sm text-muted-foreground">
            You have been invited to join an organization. Click the button below to accept.
          </p>
          <Button
            className="w-full"
            onClick={handleAccept}
            disabled={isSubmitting}
            aria-busy={isSubmitting}
          >
            {isSubmitting ? "Accepting..." : "Accept Invitation"}
          </Button>
          <p className="text-sm text-center text-muted-foreground">
            <Link to="/login" className="text-primary underline">
              Back to Sign In
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
