import { createFileRoute } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/hooks/use-auth"
import { useHealth } from "@/hooks/use-health"
import { ApiKeyPrompt } from "@/components/auth/api-key-prompt"

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
})

function SettingsPage() {
  const { isAuthenticated, apiKey, clearApiKey } = useAuth()
  const { data: health } = useHealth()

  if (!isAuthenticated) {
    return <ApiKeyPrompt />
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      <Card>
        <CardHeader>
          <CardTitle>Authentication</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="text-sm text-gray-600 mb-1">Current API Key</p>
            <code className="text-sm font-mono text-gray-800">
              {apiKey ? `${apiKey.slice(0, 8)}${"*".repeat(24)}` : "Not set"}
            </code>
          </div>
          <Button variant="outline" onClick={clearApiKey}>
            Disconnect
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Platform Info</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <dt className="text-gray-500">Version</dt>
              <dd className="font-medium">{health?.version ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Status</dt>
              <dd className="font-medium">{health?.status ?? "—"}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>
    </div>
  )
}
