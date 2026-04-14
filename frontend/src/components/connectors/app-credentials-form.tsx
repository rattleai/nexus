import { useState } from "react"
import { toast } from "sonner"
import { KeyRound, Wand2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  useAppCredentialsStatus,
  useDeleteAppCredentials,
  useRegisterAppCredentials,
  useRegisterOAuthClient,
} from "@/hooks/use-connectors"
import { parseApiError } from "@/lib/api-client"

interface AppCredentialsFormProps {
  slug: string
  connectorName: string
}

/**
 * Per-tenant OAuth app credentials panel (P3.3).
 *
 * Each tenant must register its own OAuth app before users can authenticate
 * against an OAuth connector. Two entry paths:
 *
 * 1. Manual — paste the client_id / client_secret from the provider's
 *    developer console. Works for every OAuth provider.
 * 2. Dynamic Client Registration (RFC 7591) — a single button for
 *    providers that advertise a DCR endpoint via RFC 9728/8414.
 */
export function AppCredentialsForm({ slug, connectorName }: AppCredentialsFormProps) {
  const { data: status } = useAppCredentialsStatus(slug)
  const register = useRegisterAppCredentials()
  const registerClient = useRegisterOAuthClient()
  const remove = useDeleteAppCredentials()

  const [clientId, setClientId] = useState("")
  const [clientSecret, setClientSecret] = useState("")
  const [webhookSecret, setWebhookSecret] = useState("")
  const [redirectUri, setRedirectUri] = useState("")

  const handleManualSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await register.mutateAsync({
        slug,
        body: {
          client_id: clientId.trim(),
          client_secret: clientSecret.trim(),
          webhook_secret: webhookSecret.trim() || undefined,
          redirect_uri_override: redirectUri.trim() || undefined,
        },
      })
      toast.success(`OAuth app registered for ${connectorName}`)
      setClientId("")
      setClientSecret("")
      setWebhookSecret("")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  const handleDcrClick = async () => {
    const origin = window.location.origin
    try {
      await registerClient.mutateAsync({
        slug,
        body: {
          client_name: `${connectorName} (auto-registered)`,
          redirect_uris: [`${origin}/auth/callback/connector`],
        },
      })
      toast.success("OAuth client auto-registered via DCR")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  const handleDelete = async () => {
    if (!confirm(`Delete OAuth app credentials for ${connectorName}?`)) return
    try {
      await remove.mutateAsync(slug)
      toast.success("OAuth app credentials removed")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <KeyRound className="h-4 w-4" />
          OAuth App Credentials
        </CardTitle>
        <CardDescription>
          Each tenant registers its own OAuth app so tokens and client secrets
          are never shared across tenants. Secrets are encrypted at rest.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {status?.is_registered ? (
          <div className="space-y-4">
            <div className="flex items-center gap-3 rounded-md border bg-muted/30 p-3">
              <Badge variant="secondary">Registered</Badge>
              <div className="text-sm">
                <div className="font-mono">{status.client_id_preview}</div>
                {status.redirect_uri_override && (
                  <div className="text-xs text-muted-foreground">
                    Redirect: {status.redirect_uri_override}
                  </div>
                )}
              </div>
              <div className="flex-1" />
              <Button variant="outline" size="sm" onClick={handleDelete}>
                Rotate / delete
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <Button
              variant="outline"
              size="sm"
              onClick={handleDcrClick}
              disabled={registerClient.isPending}
              className="w-full"
            >
              <Wand2 className="mr-2 h-4 w-4" />
              {registerClient.isPending
                ? "Registering..."
                : "Auto-register via Dynamic Client Registration (RFC 7591)"}
            </Button>

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-background px-2 text-muted-foreground">
                  or paste manually
                </span>
              </div>
            </div>

            <form onSubmit={handleManualSubmit} className="space-y-3">
              <div>
                <Label htmlFor={`${slug}-client-id`}>Client ID</Label>
                <Input
                  id={`${slug}-client-id`}
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  required
                  placeholder="Paste from the provider's developer console"
                />
              </div>
              <div>
                <Label htmlFor={`${slug}-client-secret`}>Client secret</Label>
                <Input
                  id={`${slug}-client-secret`}
                  type="password"
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  required
                />
              </div>
              <div>
                <Label htmlFor={`${slug}-webhook-secret`}>
                  Webhook signing secret (optional)
                </Label>
                <Input
                  id={`${slug}-webhook-secret`}
                  type="password"
                  value={webhookSecret}
                  onChange={(e) => setWebhookSecret(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor={`${slug}-redirect-uri`}>
                  Redirect URI override (optional)
                </Label>
                <Input
                  id={`${slug}-redirect-uri`}
                  value={redirectUri}
                  onChange={(e) => setRedirectUri(e.target.value)}
                  placeholder="Only needed for exact-match providers"
                />
              </div>
              <Button
                type="submit"
                disabled={register.isPending || !clientId || !clientSecret}
                className="w-full"
              >
                {register.isPending ? "Saving..." : "Save OAuth app credentials"}
              </Button>
            </form>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
