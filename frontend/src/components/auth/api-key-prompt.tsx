import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/hooks/use-auth"

export function ApiKeyPrompt() {
  const { setApiKey } = useAuth()
  const [value, setValue] = useState("")

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (trimmed) {
      setApiKey(trimmed)
    }
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
              <Input
                type="password"
                placeholder="sk_..."
                value={value}
                onChange={(e) => setValue(e.target.value)}
                autoFocus
              />
            </div>
            <Button type="submit" className="w-full" disabled={!value.trim()}>
              Connect
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
