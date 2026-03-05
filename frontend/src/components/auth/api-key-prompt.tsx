import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/hooks/use-auth"

export function ApiKeyPrompt() {
  const { setApiKey } = useAuth()
  const [value, setValue] = useState("")
  const [error, setError] = useState("")

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) return
    if (trimmed.length < 10) {
      setError("API key is too short")
      return
    }
    setError("")
    setApiKey(trimmed)
  }

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-lg font-semibold text-gray-900">Enter API Key</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <p className="text-sm text-gray-600">
                Enter your API key to access the platform. You can find it in your tenant settings.
              </p>
              <Label htmlFor="api-key-input" className="sr-only">
                API Key
              </Label>
              <Input
                id="api-key-input"
                type="password"
                placeholder="sk_..."
                value={value}
                onChange={(e) => {
                  setValue(e.target.value)
                  if (error) setError("")
                }}
                aria-invalid={!!error}
                aria-describedby={error ? "api-key-error" : undefined}
                autoFocus
              />
              {error && (
                <p id="api-key-error" className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={!value.trim()}>
              Connect
            </Button>
          </form>
          <div className="mt-4 pt-4 border-t text-center">
            <p className="text-sm text-gray-600">
              Or{" "}
              <a href="/login" className="text-primary underline">
                sign in with email
              </a>
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
