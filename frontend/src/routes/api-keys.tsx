import { useState } from "react"
import { createFileRoute } from "@tanstack/react-router"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/use-api-keys"
import { useAuth } from "@/hooks/use-auth"
import { ApiKeyPrompt } from "@/components/auth/api-key-prompt"

export const Route = createFileRoute("/api-keys")({
  component: ApiKeysPage,
})

function ApiKeysPage() {
  const { isAuthenticated } = useAuth()

  if (!isAuthenticated) {
    return <ApiKeyPrompt />
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">API Keys</h1>
        <CreateKeyButton />
      </div>
      <ApiKeysTable />
    </div>
  )
}

function CreateKeyButton() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const createKey = useCreateApiKey()

  const handleCreate = async () => {
    try {
      const result = await createKey.mutateAsync({ name: name || "default" })
      setCreatedKey(result.raw_key)
      toast.success("API key created")
    } catch {
      toast.error("Failed to create API key")
    }
  }

  const handleClose = () => {
    setOpen(false)
    setName("")
    setCreatedKey(null)
  }

  return (
    <>
      <Button onClick={() => setOpen(true)} aria-label="Create new API key">
        Create Key
      </Button>
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogHeader>
          <DialogTitle>{createdKey ? "Key Created" : "Create API Key"}</DialogTitle>
        </DialogHeader>
        <DialogContent>
          {createdKey ? (
            <div className="space-y-3">
              <p className="text-sm text-gray-600">
                Copy this key now. You won't be able to see it again.
              </p>
              <code className="block p-3 bg-gray-100 rounded text-sm break-all font-mono" role="textbox" aria-label="New API key">
                {createdKey}
              </code>
              <Button
                variant="outline"
                className="w-full"
                onClick={() => {
                  navigator.clipboard.writeText(createdKey)
                  toast.success("Copied to clipboard")
                }}
              >
                Copy to clipboard
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <Label htmlFor="key-name">Key name</Label>
              <Input
                id="key-name"
                placeholder="e.g. production, staging"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={255}
              />
            </div>
          )}
        </DialogContent>
        <DialogFooter>
          {createdKey ? (
            <Button onClick={handleClose}>Done</Button>
          ) : (
            <>
              <Button variant="outline" onClick={handleClose}>Cancel</Button>
              <Button onClick={handleCreate} disabled={createKey.isPending}>
                {createKey.isPending ? "Creating..." : "Create"}
              </Button>
            </>
          )}
        </DialogFooter>
      </Dialog>
    </>
  )
}

function ApiKeysTable() {
  const { data: keys, isLoading, error, refetch } = useApiKeys()
  const revokeKey = useRevokeApiKey()

  if (isLoading) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <CardContent className="p-6 text-center space-y-3">
          <p className="text-gray-500">Failed to load API keys</p>
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            Retry
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (!keys?.length) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-gray-500">
          No API keys yet. Create one to get started.
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Active Keys</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Name</TableHead>
              <TableHead scope="col">Status</TableHead>
              <TableHead scope="col">Rate Limit</TableHead>
              <TableHead scope="col">Created</TableHead>
              <TableHead scope="col" className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {keys.map((key) => (
              <TableRow key={key.id}>
                <TableCell className="font-medium">{key.name}</TableCell>
                <TableCell>
                  <Badge variant={key.active ? "default" : "secondary"}>
                    {key.active ? "Active" : "Revoked"}
                  </Badge>
                </TableCell>
                <TableCell>{key.rate_limit ?? "Unlimited"}/min</TableCell>
                <TableCell>{new Date(key.created_at).toLocaleDateString()}</TableCell>
                <TableCell className="text-right">
                  {key.active && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={revokeKey.isPending}
                      aria-label={`Revoke API key ${key.name}`}
                      onClick={() => {
                        revokeKey.mutate(key.id, {
                          onSuccess: () => toast.success("Key revoked"),
                          onError: () => toast.error("Failed to revoke key"),
                        })
                      }}
                    >
                      Revoke
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
