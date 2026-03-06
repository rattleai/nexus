import { useState } from "react"
import { createLazyFileRoute } from "@tanstack/react-router"
import { toast } from "sonner"
import type { ColumnDef } from "@tanstack/react-table"
import { Key, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { AuthGuard } from "@/components/auth/auth-guard"
import { ResourcePage } from "@/components/resource-page"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { CopyButton } from "@/components/copy-button"
import { FormDialog } from "@/components/form-dialog"
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/use-api-keys"
import { parseApiError } from "@/lib/api-client"
import { formatDate } from "@/lib/format"
import type { ApiKey } from "@/types/api"

export const Route = createLazyFileRoute("/api-keys")({
  component: ApiKeysPage,
})

const columns: ColumnDef<ApiKey>[] = [
  { accessorKey: "name", header: "Name" },
  {
    accessorKey: "active",
    header: "Status",
    cell: ({ row }) => (
      <Badge variant={row.original.active ? "default" : "secondary"}>
        {row.original.active ? "Active" : "Revoked"}
      </Badge>
    ),
  },
  {
    accessorKey: "scopes",
    header: "Scopes",
    cell: ({ row }) => (
      <span className="text-xs text-muted-foreground">
        {row.original.scopes?.join(", ") || "All"}
      </span>
    ),
  },
  {
    accessorKey: "rate_limit",
    header: "Rate Limit",
    cell: ({ row }) => `${row.original.rate_limit ?? "Unlimited"}/min`,
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ row }) => formatDate(row.original.created_at),
  },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => <RevokeButton apiKey={row.original} />,
  },
]

function RevokeButton({ apiKey }: { apiKey: ApiKey }) {
  const revokeKey = useRevokeApiKey()

  if (!apiKey.active) return null

  return (
    <ConfirmDialog
      title="Revoke API Key"
      description={`Are you sure you want to revoke "${apiKey.name}"? This cannot be undone.`}
      variant="destructive"
      confirmLabel="Revoke"
      onConfirm={async () => {
        try {
          await revokeKey.mutateAsync(apiKey.id)
          toast.success("API key revoked")
        } catch (err) {
          const e = await parseApiError(err)
          toast.error(e.detail)
        }
      }}
    >
      <Button variant="ghost" size="sm">
        Revoke
      </Button>
    </ConfirmDialog>
  )
}

function ApiKeysPage() {
  const queryResult = useApiKeys()
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <AuthGuard>
      <ResourcePage
        title="API Keys"
        description="Manage API keys for programmatic access."
        queryResult={queryResult}
        columns={columns}
        searchKey="name"
        searchPlaceholder="Search keys..."
        emptyState={{
          icon: Key,
          title: "No API keys yet",
          description: "Create an API key to get started with programmatic access.",
          action: (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Create Key
            </Button>
          ),
        }}
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Key
          </Button>
        }
      />
      <CreateKeyDialog open={createOpen} onOpenChange={setCreateOpen} />
    </AuthGuard>
  )
}

function CreateKeyDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [name, setName] = useState("")
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const createKey = useCreateApiKey()

  const handleCreate = async () => {
    try {
      const result = await createKey.mutateAsync({ name: name || "default" })
      setCreatedKey(result.raw_key)
      toast.success("API key created")
    } catch (err) {
      const e = await parseApiError(err)
      toast.error(e.detail)
    }
  }

  const handleClose = () => {
    onOpenChange(false)
    setName("")
    setCreatedKey(null)
  }

  if (createdKey) {
    return (
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Key Created</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Copy this key now. You won't be able to see it again.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 p-3 bg-muted rounded text-sm break-all font-mono">
                {createdKey}
              </code>
              <CopyButton value={createdKey} />
            </div>
            <Button onClick={handleClose} className="w-full">
              Done
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={handleClose}
      title="Create API Key"
      description="Give your key a descriptive name."
      isPending={createKey.isPending}
      onSubmit={handleCreate}
      submitLabel="Create"
    >
      <div className="space-y-2">
        <Label htmlFor="key-name">Key name</Label>
        <Input
          id="key-name"
          placeholder="e.g. production, staging"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={255}
          autoFocus
        />
      </div>
    </FormDialog>
  )
}
